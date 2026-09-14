"""FastAPI surface over the spec2cad pipeline.

Thin by design: every decision lives in the library, and the API only moves data
and enforces the one rule the transport layer is responsible for -- a STEP
download is refused with 409 while the release gate is blocking, and the reason
is returned in the body rather than as a bare error.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from spec2cad.cad.executor import export_step, export_stl
from spec2cad.extractors.base import backend_label, select_backend
from spec2cad.cad.compiler import parameter_table
from spec2cad.pipeline import (
    InterfaceChangeRequiresAcknowledgement,
    RevisionResult,
    interface_critical,
    repair,
    revise,
    run,
)
from spec2cad.preview import NoRegion, render_evidence_preview
from spec2cad.repair.repair_planner import UnsafeRepairRequiresAcknowledgement
from spec2cad.store import Store

BUILD_DIR = Path("build")
UPLOAD_DIR = BUILD_DIR / "uploads"
ARTIFACT_DIR = BUILD_DIR / "artifacts"
EXAMPLE_DIR = Path("examples/motor_adapter")

app = FastAPI(title="Spec2CAD", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store()

# Live pipeline results, keyed by run id. The store holds the durable audit
# trail; this cache holds the built geometry so a download does not rebuild.
_runs: dict[str, object] = {}


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def _evidence_json(run_result) -> list[dict]:
    out = []
    for e in run_result.evidence.items:
        out.append({
            "id": e.id,
            "target": e.target.value,
            "kind": e.kind.value,
            "value": e.value,
            "unit": e.unit,
            "source": {
                "file": e.source.file,
                "modality": e.source.modality.value,
                "page": e.source.page,
                "region": list(e.source.region) if e.source.region else None,
                "detail": e.source.detail,
            },
            "extraction_method": e.extraction_method.value,
            "confidence": e.confidence,
            "authority": e.authority.value,
            "is_explicit_annotation": e.is_explicit_annotation,
            "is_fixture": e.is_fixture,
            "raw_text": e.raw_text,
            "original_value": e.original_value,
            "has_preview": e.source.region is not None,
        })
    return out


def _check_json(c) -> dict:
    return {
        "id": c.id, "stage": c.stage.value, "name": c.name, "status": c.status.value,
        "expected": c.expected, "actual": c.actual,
        "required_value": c.required_value, "measured_value": c.measured_value,
        "conflict_class": c.conflict_class.value if c.conflict_class else None,
        "responsible_parameters": c.responsible_parameters,
        "message": c.message,
    }


def _revision_json(rev: RevisionResult) -> dict:
    intent = rev.intent
    return {
        "revision": rev.revision,
        "parent_revision": intent.parent_revision,
        "lineage": intent.lineage_summary(),
        "applied_proposal": intent.applied_proposal,
        "approved_by": intent.approved_by,
        "changes": [
            {"parameter": c.parameter, "before": c.before, "after": c.after,
             "reason": c.reason}
            for c in intent.changes
        ],
        "part": {
            "name": intent.part.name,
            "material": intent.part.material,
            "manufacturing_process": intent.part.manufacturing_process,
        },
        "parameters": {
            name: {
                "value": p.value, "unit": p.unit, "status": p.status.value,
                "provenance": p.provenance, "authority": p.authority.value,
                "is_explicit": p.is_explicit, "derivation": p.derivation,
                "competing_values": p.competing_values,
            }
            for name, p in intent.parameters.items()
        },
        "constraints": [
            {"id": c.id, "type": c.type, "value": c.value, "unit": c.unit,
             "severity": c.severity.value, "description": c.description}
            for c in intent.constraints
        ],
        "feature_sequence": rev.program.feature_sequence() if rev.program else [],
        # each feature with its numeric fields resolved, so the timeline can say
        # what an operation actually is rather than only naming it
        "operations": (
            rev.program.describe(parameter_table(rev.intent)) if rev.program else []
        ),
        "editable_parameters": [
            {
                "name": name,
                "value": p.value,
                "unit": p.unit,
                "interface_critical": name in interface_critical([name]),
            }
            for name, p in rev.intent.parameters.items()
            if isinstance(p.value, (int, float))
        ],
        "preflight": [_check_json(c) for c in rev.preflight.checks] if rev.preflight else [],
        "measured": [_check_json(c) for r in rev.measured for c in r.checks],
        "cross_checks": [_check_json(c) for c in rev.cross_checks],
        "build_error": rev.build_error,
        "release": {
            "status": rev.decision.status.value if rev.decision else "unknown",
            "step_export_allowed": rev.released,
            "watermark": rev.decision.mesh_watermark if rev.decision else None,
            "reasons": rev.decision.reasons if rev.decision else [],
            "explanation": rev.decision.explain() if rev.decision else "",
            "responsible_parameters": (
                rev.decision.responsible_parameters if rev.decision else []
            ),
        },
        "proposals": [
            {"id": p.id, "title": p.title, "safety": p.safety.value,
             "updates": p.updates, "rationale": p.rationale,
             "consequence": p.consequence, "recommended": p.recommended,
             "auto_applicable": p.auto_applicable}
            for p in rev.proposals
        ],
        "script": rev.script,
    }


def _run_json(run_id: str, run_result) -> dict:
    return {
        "run_id": run_id,
        "sketch_backend": run_result.sketch_backend,
        "sketch_fell_back": run_result.sketch_fell_back,
        "sketch_fallback_reason": run_result.sketch_fallback_reason,
        "contains_fixture_evidence": run_result.evidence.contains_fixture_data,
        "evidence": _evidence_json(run_result),
        "revisions": [_revision_json(r) for r in run_result.revisions],
        "latest_revision": run_result.latest.revision,
    }


def _persist(run_id: str, run_result) -> None:
    for rev in run_result.revisions:
        store.save_revision(run_id, rev.intent, _revision_json(rev))


def _require(run_id: str):
    result = _runs.get(run_id)
    if result is None:
        raise HTTPException(404, f"unknown run {run_id!r} (not in this process's cache)")
    return result


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    backend = select_backend()
    return {
        "status": "ok",
        "sketch_backend": backend.value,
        "sketch_backend_label": backend_label(backend),
        "vision_available": backend.value != "fixture",
    }


@app.post("/runs/demo")
def create_demo_run(backend: Optional[str] = None) -> JSONResponse:
    """Run the bundled motor-adapter example."""
    if not (EXAMPLE_DIR / "sketch.png").exists():
        raise HTTPException(
            503, "example inputs missing; run examples/motor_adapter/generate_inputs.py"
        )
    result = run(
        EXAMPLE_DIR / "sketch.png",
        EXAMPLE_DIR / "motor_datasheet.pdf",
        EXAMPLE_DIR / "requirement.txt",
        backend,
    )
    run_id = store.create_run(
        EXAMPLE_DIR, result.evidence, result.sketch_backend,
        result.sketch_fell_back, result.sketch_fallback_reason,
    )
    _runs[run_id] = result
    _persist(run_id, result)
    return JSONResponse(_run_json(run_id, result))


@app.post("/runs")
async def create_run(
    sketch: UploadFile = File(...),
    datasheet: UploadFile = File(...),
    requirement: str = Form(...),
    backend: Optional[str] = Form(None),
) -> JSONResponse:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=UPLOAD_DIR))

    sketch_path = work / "sketch.png"
    datasheet_path = work / "motor_datasheet.pdf"
    requirement_path = work / "requirement.txt"

    with sketch_path.open("wb") as fh:
        shutil.copyfileobj(sketch.file, fh)
    with datasheet_path.open("wb") as fh:
        shutil.copyfileobj(datasheet.file, fh)
    requirement_path.write_text(requirement, encoding="utf-8")

    # An uploaded sketch has no recorded fixture, so with no API key configured
    # there is nothing to fall back to. Say so plainly.
    if select_backend(backend).value == "fixture":
        fixture = work / "sketch.fixture.json"
        if not fixture.exists():
            raise HTTPException(
                400,
                "no vision API key is configured, and an uploaded sketch has no "
                "recorded fixture to replay. Set OPENAI_API_KEY or ANTHROPIC_API_KEY "
                "in .env to extract uploaded drawings, or use POST /runs/demo to run "
                "the bundled example.",
            )

    try:
        result = run(sketch_path, datasheet_path, requirement_path, backend)
    except Exception as exc:
        raise HTTPException(422, f"pipeline failed: {type(exc).__name__}: {exc}") from exc

    run_id = store.create_run(
        work, result.evidence, result.sketch_backend,
        result.sketch_fell_back, result.sketch_fallback_reason,
    )
    _runs[run_id] = result
    _persist(run_id, result)
    return JSONResponse(_run_json(run_id, result))


@app.get("/runs")
def list_runs() -> dict:
    return {"runs": store.list_runs()}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    return JSONResponse(_run_json(run_id, _require(run_id)))


class RepairRequest(BaseModel):
    proposal_id: str
    approved_by: str = "ui-user"
    acknowledge_unsafe: bool = False


@app.post("/runs/{run_id}/repair")
def apply_repair_endpoint(run_id: str, body: RepairRequest) -> JSONResponse:
    result = _require(run_id)
    try:
        updated = repair(
            result, body.proposal_id,
            approved_by=body.approved_by,
            acknowledge_unsafe=body.acknowledge_unsafe,
        )
    except UnsafeRepairRequiresAcknowledgement as exc:
        raise HTTPException(409, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    _runs[run_id] = updated
    _persist(run_id, updated)
    return JSONResponse(_run_json(run_id, updated))


class ReviseRequest(BaseModel):
    updates: dict[str, float]
    approved_by: str = "ui-user"
    reason: str = "manual parameter edit"
    acknowledge_interface: bool = False


@app.post("/runs/{run_id}/revise")
def revise_endpoint(run_id: str, body: ReviseRequest) -> JSONResponse:
    """Derive a new revision from a hand-edited parameter.

    Repair proposals only exist while something is blocked, so without this a
    released design would be a dead end.
    """
    result = _require(run_id)
    try:
        updated = revise(
            result, body.updates,
            approved_by=body.approved_by,
            reason=body.reason,
            acknowledge_interface=body.acknowledge_interface,
        )
    except InterfaceChangeRequiresAcknowledgement as exc:
        raise HTTPException(409, str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    _runs[run_id] = updated
    _persist(run_id, updated)
    return JSONResponse(_run_json(run_id, updated))


@app.get("/runs/{run_id}/revisions")
def list_revisions(run_id: str) -> dict:
    result = _require(run_id)
    return {
        "revisions": [
            {"revision": r.revision, "lineage": r.intent.lineage_summary(),
             "released": r.released}
            for r in result.revisions
        ]
    }


def _revision_or_404(result, revision: int) -> RevisionResult:
    try:
        return result.revision(revision)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/runs/{run_id}/revisions/{revision}/model.stl")
def get_stl(run_id: str, revision: int):
    """Always available. Provisional geometry is labelled, not hidden --
    seeing the conflict is part of understanding it."""
    rev = _revision_or_404(_require(run_id), revision)
    if rev.execution is None:
        raise HTTPException(409, rev.build_error or "no geometry was produced")
    path = ARTIFACT_DIR / run_id / f"v{revision}.stl"
    if not path.exists():
        export_stl(rev.execution, path)
    return FileResponse(
        path, media_type="model/stl", filename=f"{rev.intent.part.name}_v{revision}.stl",
        headers={"X-Spec2CAD-Watermark": rev.decision.mesh_watermark or "released"},
    )


@app.get("/runs/{run_id}/revisions/{revision}/model.step")
def get_step(run_id: str, revision: int):
    """Withheld while the release gate is blocking."""
    rev = _revision_or_404(_require(run_id), revision)
    if rev.execution is None:
        raise HTTPException(409, rev.build_error or "no geometry was produced")
    if not rev.released:
        raise HTTPException(
            409,
            {
                "error": "STEP export is withheld by the release gate",
                "explanation": rev.decision.explain(),
                "reasons": rev.decision.reasons,
                "responsible_parameters": rev.decision.responsible_parameters,
            },
        )
    path = ARTIFACT_DIR / run_id / f"v{revision}.step"
    if not path.exists():
        export_step(rev.execution, path)
    return FileResponse(
        path, media_type="application/step",
        filename=f"{rev.intent.part.name}_v{revision}.step",
    )


@app.get("/runs/{run_id}/revisions/{revision}/script.py")
def get_script(run_id: str, revision: int) -> PlainTextResponse:
    rev = _revision_or_404(_require(run_id), revision)
    return PlainTextResponse(rev.script or "# no script generated")


@app.get("/runs/{run_id}/evidence/{evidence_id}/preview")
def evidence_preview(run_id: str, evidence_id: str):
    """Render the source region for a piece of evidence.

    For the datasheet these are real PyMuPDF rectangles, so the highlight lands
    on the actual text that produced the value.
    """
    result = _require(run_id)
    stored = store.get_run(run_id)
    evidence = result.evidence.get(evidence_id)
    if evidence is None:
        raise HTTPException(404, f"unknown evidence {evidence_id!r}")
    if evidence.source.region is None:
        raise HTTPException(404, "this evidence has no source region to highlight")

    input_dir = stored.input_dir if stored else EXAMPLE_DIR

    out = ARTIFACT_DIR / run_id / "previews" / f"{evidence_id}.png"
    try:
        render_evidence_preview(evidence, input_dir, out)
    except NoRegion as exc:
        raise HTTPException(404, str(exc)) from exc

    return FileResponse(out, media_type="image/png")
