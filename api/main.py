"""FastAPI surface over the spec2cad pipeline.

Thin by design: every decision lives in the library, and the API only moves data
and enforces the one rule the transport layer is responsible for -- a STEP
download is refused with 409 while the release gate is blocking, and the reason
is returned in the body rather than as a bare error.
"""

from __future__ import annotations

import os
import hmac
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from spec2cad.capabilities import HEALTH_CAPABILITY_IDS, capability_payload
from spec2cad.extractors.base import (
    DEFAULT_OPENAI_MODEL,
    backend_label,
    load_env,
    openai_model,
    reasoning_available,
    reasoning_model,
    safe_backend_error,
    select_backend,
)
from spec2cad.extractors.model_provider import (
    ModelConnection,
    ModelProvider,
    allowed_model_hosts,
)
from spec2cad.cad.compiler import parameter_table
from spec2cad.schemas.cad_ir import CADProgram
from spec2cad.schemas.assembly_ir import AssemblyProgram
from spec2cad.schemas.gdt_ir import InspectionProgram
from spec2cad.schemas.analysis_ir import AnalysisProgram
from spec2cad.store import Store
from spec2cad.public_guardrails import (
    BoundedRunCache,
    DailyAIBudget,
    PublicGuardrailMiddleware,
    PublicLimits,
)

BUILD_DIR = Path("build")
UPLOAD_DIR = BUILD_DIR / "uploads"
ARTIFACT_DIR = BUILD_DIR / "artifacts"
EXAMPLE_DIR = Path("examples/motor_adapter")

app = FastAPI(title="Spec2CAD", version="1.0.0")
load_env()
limits = PublicLimits.from_env()

# The deployed frontend lives on a different origin from this API, so the
# allowed list is configuration rather than a constant. SPEC2CAD_ALLOWED_ORIGINS
# is a comma-separated list; local dev origins are always included.
_DEFAULT_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5174", "http://localhost:4173",
]
_configured = [
    o.strip()
    for o in os.environ.get("SPEC2CAD_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEFAULT_ORIGINS + _configured,
    # Preview origins are opt-in because wildcard browser access broadens abuse.
    allow_origin_regex=(
        r"https://spec2cad[\w-]*\.vercel\.app"
        if os.environ.get("SPEC2CAD_ALLOW_VERCEL_PREVIEWS", "0") == "1"
        else None
    ),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Server-Timing", "X-Request-ID", "X-RateLimit-Limit",
        "X-RateLimit-Remaining", "X-Spec2CAD-Queue-Wait-Ms",
    ],
)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=1)
app.add_middleware(PublicGuardrailMiddleware, limits=limits)

store = Store()
ai_budget = DailyAIBudget(
    store, limits.ai_units_per_client_day, limits.ai_units_global_day
)

# Live pipeline results, keyed by run id. The store holds the durable audit
# trail; this cache holds the built geometry so a download does not rebuild.
_runs = BoundedRunCache(limits.max_cached_runs)


def run(*args, **kwargs):
    """Lazy pipeline entrypoint; kept patchable for API boundary tests."""
    from spec2cad.pipeline import run as run_pipeline

    return run_pipeline(*args, **kwargs)


class InspectionRequest(BaseModel):
    program: CADProgram
    parameters: dict[str, float] = Field(default_factory=dict, max_length=128)
    inspection: InspectionProgram


class AnalysisRequest(BaseModel):
    program: CADProgram
    parameters: dict[str, float] = Field(default_factory=dict, max_length=128)
    analysis: AnalysisProgram


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


def _operations_json(rev: Any) -> list[dict]:
    """Program operations joined to what the kernel measured for each one.

    The two halves are deliberately kept distinct in the payload. `fields` is
    what we asked the kernel to do; `measured` is what the solid looked like
    afterwards. A feature with no `measured` block did not get as far as being
    built, and the UI must not imply otherwise.
    """
    if rev.program is None:
        return []
    described = rev.program.describe(parameter_table(rev.intent))
    by_id = {
        m.operation_id: m
        for m in (rev.execution.measurements if rev.execution else [])
    }
    for entry in described:
        m = by_id.get(entry["id"])
        entry["measured"] = None if m is None else {
            "volume": round(m.volume, 4),
            "volume_delta": round(m.volume_delta, 4),
            "is_valid": m.is_valid,
            "solid_count": m.solid_count,
            "seconds": round(m.seconds, 4),
            "no_op": m.no_op,
        }
    return described


def _revision_json(rev: Any) -> dict:
    from spec2cad.pipeline import interface_critical
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
        "intent_graph": (
            rev.intent_graph.model_dump(mode="json") if rev.intent_graph else None
        ),
        "feature_sequence": rev.program.feature_sequence() if rev.program else [],
        # Each feature with its numeric fields resolved AND what the kernel
        # measured after building it. The resolved fields alone are only the
        # program restated; the measurement is the evidence that it happened.
        "operations": _operations_json(rev),
        "derived_geometry": (
            rev.execution.context.derived if rev.execution else {}
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
        "backend_evidence": rev.backend_evidence,
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
        "reasoning_backend": run_result.reasoning_backend,
        "reasoning_fell_back": run_result.reasoning_fell_back,
        "reasoning_fallback_reason": run_result.reasoning_fallback_reason,
        "unsupported_features": run_result.unsupported_features,
        "clarification_questions": run_result.clarification_questions,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "kind": message.kind,
                "created_at": message.created_at,
            }
            for message in run_result.messages
        ],
        "feature_requests": [
            request.model_dump(mode="json")
            for request in run_result.evidence.feature_requests
        ],
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


def _retry_after_midnight() -> str:
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return str(max(1, int((tomorrow - now).total_seconds())))


def _reserve_ai(request: Request, units: int) -> None:
    if units <= 0:
        return
    key = getattr(request.state, "client_hash", "unknown")
    try:
        ai_budget.reserve(key, units)
    except ValueError as exc:
        scope = str(exc)
        detail = (
            "your daily AI generation limit has been reached"
            if scope == "client_daily_limit"
            else "the public demo's daily AI budget has been reached"
        )
        raise HTTPException(
            429, detail, headers={"Retry-After": _retry_after_midnight()}
        ) from exc


def _validate_text(value: str, *, name: str = "instruction") -> str:
    text = value.strip()
    if len(text) > limits.max_requirement_chars:
        raise HTTPException(
            413,
            f"{name} exceeds the {limits.max_requirement_chars}-character public limit",
        )
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise HTTPException(422, f"{name} contains unsupported control characters")
    return text


def _request_model_connection(
    api_key: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
) -> ModelConnection | None:
    """Validate an ephemeral caller-owned credential without persisting it."""
    metadata_supplied = any(value and value.strip() for value in (provider, model, base_url))
    if not api_key:
        if metadata_supplied:
            raise HTTPException(400, "model provider settings require an API key")
        return None
    try:
        selected = ModelProvider(
            (provider or ("openai_compatible" if base_url else "openai")).strip().lower()
        )
        model_name = (model or (DEFAULT_OPENAI_MODEL if selected is ModelProvider.OPENAI else "")).strip()
        if not model_name:
            raise ValueError("a custom model provider requires an explicit model name")
        return ModelConnection(
            provider=selected,
            api_key=api_key,
            model=model_name,
            base_url=base_url.strip() if base_url else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _save_upload(upload: UploadFile, path: Path, max_bytes: int) -> None:
    written = 0
    with path.open("wb") as fh:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"{upload.filename or 'upload'} is too large")
            fh.write(chunk)


def _validate_image(path: Path) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
        if width * height > limits.max_image_pixels:
            raise HTTPException(413, "image pixel count exceeds the public limit")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(422, "uploaded sketch is not a valid image") from exc


def _validate_pdf(path: Path) -> None:
    import fitz

    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                raise HTTPException(422, "encrypted PDFs are not accepted")
            if document.page_count > limits.max_pdf_pages:
                raise HTTPException(
                    413, f"PDF exceeds the {limits.max_pdf_pages}-page public limit"
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "uploaded datasheet is not a valid PDF") from exc


def _require_admin_token(value: Optional[str]) -> None:
    expected = os.environ.get("SPEC2CAD_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(404, "administrative API is disabled")
    if not value or not hmac.compare_digest(value, expected):
        raise HTTPException(401, "admin token required")


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    backend = select_backend()
    semantic_model_available = reasoning_available()
    multimodal_available = (
        semantic_model_available and backend.value == "openai"
    )
    return {
        "status": "ok",
        "sketch_backend": backend.value,
        "sketch_backend_label": backend_label(backend),
        "vision_available": backend.value != "fixture",
        "vision_model": openai_model() if backend.value == "openai" else None,
        "reasoning_available": semantic_model_available,
        "reasoning_model": reasoning_model() if semantic_model_available else None,
        "model_connections": {
            "bring_your_own_key": True,
            "providers": [provider.value for provider in ModelProvider],
            "compatible_hosts": list(allowed_model_hosts()),
            "credentials_persisted": False,
        },
        "inputs": {
            "natural_language": semantic_model_available,
            "engineering_sketch": backend.value != "fixture",
            "technical_pdf": True,
            "multimodal_semantic_fusion": multimodal_available,
        },
        "public_limits": {
            "requests_per_minute": limits.requests_per_minute,
            "ai_units_per_client_day": limits.ai_units_per_client_day,
            "max_requirement_chars": limits.max_requirement_chars,
            "max_conversation_messages": limits.max_conversation_messages,
            "max_concurrent_jobs": limits.max_concurrent_jobs,
            "job_queue_timeout_ms": limits.job_queue_timeout_ms,
            "max_cached_runs": limits.max_cached_runs,
        },
        # Keep the compact legacy list while exposing the independently
        # classified source-of-truth records alongside it.
        "capabilities": list(HEALTH_CAPABILITY_IDS),
        "capability_registry": capability_payload(),
    }


@app.post("/assemblies/evaluate")
def evaluate_assembly_endpoint(
    program: AssemblyProgram,
    x_spec2cad_admin_token: Optional[str] = Header(None),
) -> dict:
    """Execute every component, apply transforms, then validate mates/collisions."""
    from spec2cad.cad.assembly import execute_assembly
    from spec2cad.cad.executor import ExecutionError

    _require_admin_token(x_spec2cad_admin_token)
    try:
        result = execute_assembly(program)
    except (ValueError, ExecutionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "name": program.name,
        "passed": result.passed,
        "component_count": len(result.components),
        "checks": [check.__dict__ for check in result.checks],
    }


@app.post("/inspection/evaluate")
def evaluate_inspection_endpoint(
    body: InspectionRequest,
    x_spec2cad_admin_token: Optional[str] = Header(None),
) -> dict:
    """Build one typed CAD program and independently evaluate its GD&T controls."""
    from spec2cad.cad.executor import ExecutionError, execute
    from spec2cad.validation.gdt import inspect_gdt

    _require_admin_token(x_spec2cad_admin_token)
    try:
        execution = execute(body.program, body.parameters)
        results = inspect_gdt(execution.shape, body.inspection)
    except (ValueError, ExecutionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "passed": all(result.passed for result in results),
        "results": [result.__dict__ for result in results],
    }


@app.post("/analyses/evaluate")
def evaluate_analysis_endpoint(
    body: AnalysisRequest,
    x_spec2cad_admin_token: Optional[str] = Header(None),
) -> dict:
    """Build one typed CAD program and run explicit-assumption analyses."""
    from spec2cad.analysis import run_analyses
    from spec2cad.cad.executor import ExecutionError, execute

    _require_admin_token(x_spec2cad_admin_token)
    try:
        execution = execute(body.program, body.parameters)
        results = run_analyses(execution.shape, body.analysis)
    except (ValueError, ExecutionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "passed": all(result.passed is not False for result in results),
        "results": [result.__dict__ for result in results],
    }


@app.post("/runs/demo")
def create_demo_run(request: Request, backend: Optional[str] = None) -> JSONResponse:
    """Run the bundled motor-adapter example."""
    if not (EXAMPLE_DIR / "sketch.png").exists():
        raise HTTPException(
            503, "example inputs missing; run examples/motor_adapter/generate_inputs.py"
        )
    selected = select_backend(backend)
    semantic = reasoning_available()
    _reserve_ai(request, int(semantic) + int(
        selected.value != "fixture"
        and not (semantic and selected.value == "openai")
    ))
    result = run(
        EXAMPLE_DIR / "sketch.png",
        EXAMPLE_DIR / "motor_datasheet.pdf",
        EXAMPLE_DIR / "requirement.txt",
        backend,
        use_reasoning=True,
    )
    run_id = store.create_run(
        EXAMPLE_DIR, result.evidence, result.sketch_backend,
        result.sketch_fell_back, result.sketch_fallback_reason,
    )
    _runs[run_id] = result
    _persist(run_id, result)
    return JSONResponse(_run_json(run_id, result))


@app.post("/runs")
def create_run(
    request: Request,
    sketch: Optional[UploadFile] = File(None),
    datasheet: Optional[UploadFile] = File(None),
    requirement: Optional[str] = Form(None),
    backend: Optional[str] = Form(None),
    model_provider: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
    model_base_url: Optional[str] = Form(None),
    x_spec2cad_model_api_key: Optional[str] = Header(
        None, alias="X-Spec2CAD-Model-API-Key",
    ),
) -> JSONResponse:
    requirement_text = _validate_text(requirement or "")
    model_connection = _request_model_connection(
        x_spec2cad_model_api_key,
        model_provider,
        model_name,
        model_base_url,
    )
    if sketch is None and datasheet is None and not requirement_text:
        raise HTTPException(
            400,
            "add at least one source: a sketch, a datasheet, or a written instruction",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=UPLOAD_DIR))

    sketch_path: Optional[Path] = None
    datasheet_path: Optional[Path] = None
    requirement_path: Optional[Path] = None

    try:
        if sketch is not None:
            suffix = Path(sketch.filename or "").suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                suffix = ".png"
            sketch_path = work / f"sketch{suffix}"
            _save_upload(sketch, sketch_path, limits.max_image_bytes)
            _validate_image(sketch_path)
        if datasheet is not None:
            datasheet_path = work / "motor_datasheet.pdf"
            _save_upload(datasheet, datasheet_path, limits.max_pdf_bytes)
            _validate_pdf(datasheet_path)
    except HTTPException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    if requirement_text:
        requirement_path = work / "requirement.txt"
        requirement_path.write_text(requirement_text, encoding="utf-8")

    try:
        selected = (
            select_backend(backend, model_connection)
            if sketch_path is not None else None
        )
        semantic = (
            reasoning_available(model_connection)
            if model_connection else reasoning_available()
        )
        _reserve_ai(
            request,
            0 if model_connection else (
                int(semantic)
                + int(
                    selected is not None
                    and selected.value != "fixture"
                    and not (semantic and selected.value == "openai")
                )
            ),
        )
    except HTTPException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except ValueError as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc

    # An uploaded sketch has no recorded fixture, so with no API key configured
    # there is nothing to fall back to. Say so plainly.
    if (
        sketch_path is not None
        and select_backend(backend, model_connection).value == "fixture"
    ):
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(
            400,
            "no vision API key is configured, and an uploaded sketch has no "
            "recorded fixture to replay. Add a vision API key, remove the sketch "
            "and compile the other sources, or run the bundled example.",
        )

    try:
        result = run(
            sketch_path,
            datasheet_path,
            requirement_path,
            backend,
            use_reasoning=True,
            model_connection=model_connection,
        )
    except Exception as exc:
        shutil.rmtree(work, ignore_errors=True)
        provider_modules = ("openai", "anthropic", "httpx")
        detail = (
            safe_backend_error(exc)
            if type(exc).__module__.startswith(provider_modules)
            else f"{type(exc).__name__}: {exc}"
        )
        raise HTTPException(422, f"pipeline failed: {detail}") from exc

    run_id = store.create_run(
        work, result.evidence, result.sketch_backend,
        result.sketch_fell_back, result.sketch_fallback_reason,
    )
    _runs[run_id] = result
    _persist(run_id, result)
    return JSONResponse(_run_json(run_id, result))


@app.get("/runs")
def list_runs(x_spec2cad_admin_token: Optional[str] = Header(None)) -> dict:
    _require_admin_token(x_spec2cad_admin_token)
    return {"runs": store.list_runs()}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> JSONResponse:
    return JSONResponse(_run_json(run_id, _require(run_id)))


@app.get("/runs/{run_id}/sources/{filename}")
def get_source(run_id: str, filename: str):
    """Return one supplied document for the evidence editor.

    The filename must occur in this run's evidence and resolve directly inside
    its input directory. Engineering-rule citations are evidence sources too,
    but they are not uploaded files and therefore correctly return 404 here.
    """
    result = _require(run_id)
    allowed = {
        e.source.file
        for e in result.evidence.items
        if e.source.modality.value != "engineering_rule"
    }
    if filename not in allowed or Path(filename).name != filename:
        raise HTTPException(404, f"unknown source {filename!r}")

    stored = store.get_run(run_id)
    input_dir = (stored.input_dir if stored else EXAMPLE_DIR).resolve()
    source = (input_dir / filename).resolve()
    if source.parent != input_dir or not source.is_file():
        raise HTTPException(404, f"source file not found: {filename!r}")
    return FileResponse(source)


class RepairRequest(BaseModel):
    proposal_id: str
    approved_by: str = "ui-user"
    acknowledge_unsafe: bool = False


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1)
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    model_base_url: Optional[str] = None


@app.post("/runs/{run_id}/messages")
def continue_run_endpoint(
    run_id: str,
    body: ChatTurnRequest,
    request: Request,
    x_spec2cad_model_api_key: Optional[str] = Header(
        None, alias="X-Spec2CAD-Model-API-Key",
    ),
) -> JSONResponse:
    """Continue the same engineering conversation as a new audited revision."""
    from spec2cad.pipeline import continue_conversation

    result = _require(run_id)
    message = _validate_text(body.message, name="message")
    if len(result.messages) >= limits.max_conversation_messages:
        raise HTTPException(
            409,
            "this public conversation reached its turn limit; start a new design",
        )
    model_connection = _request_model_connection(
        x_spec2cad_model_api_key,
        body.model_provider,
        body.model_name,
        body.model_base_url,
    )
    _reserve_ai(
        request,
        0 if model_connection else int(reasoning_available()),
    )
    try:
        updated = continue_conversation(
            result, message, model_connection=model_connection,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _runs[run_id] = updated
    _persist(run_id, updated)
    return JSONResponse(_run_json(run_id, updated))


@app.post("/runs/{run_id}/repair")
def apply_repair_endpoint(run_id: str, body: RepairRequest) -> JSONResponse:
    from spec2cad.pipeline import repair
    from spec2cad.repair.repair_planner import UnsafeRepairRequiresAcknowledgement

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
    from spec2cad.pipeline import InterfaceChangeRequiresAcknowledgement, revise

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
    from spec2cad.cad.executor import export_stl

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
    from spec2cad.cad.executor import export_step

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
    from spec2cad.preview import NoRegion, render_evidence_preview

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
