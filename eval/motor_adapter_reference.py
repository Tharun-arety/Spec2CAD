"""Canonical deterministic reference for the R1 motor-adapter baseline."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from spec2cad.cad.executor import export_step, import_step
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run, verify_exported_step
from spec2cad.validation import measure as M


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "motor_adapter"
REFERENCE = EXAMPLE / "r1_reference.json"
REFERENCE_SCHEMA_VERSION = "1.0.0"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _content_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _geometry_fingerprint(shape) -> dict:
    extents = M.plate_extents(shape)
    circles = sorted(
        M.circular_features(M.top_face(shape)),
        key=lambda item: (round(item.radius, 6), round(item.x, 6), round(item.y, 6)),
    )
    return {
        "valid": bool(shape.isValid()),
        "solid_count": len(shape.Solids()),
        "width_mm": _rounded(extents.width),
        "height_mm": _rounded(extents.height),
        "thickness_mm": _rounded(extents.thickness),
        "volume_mm3": _rounded(shape.Volume()),
        "circular_features": [
            {
                "diameter_mm": _rounded(2 * item.radius),
                "x_mm": _rounded(item.x),
                "y_mm": _rounded(item.y),
            }
            for item in circles
        ],
    }


def _revision_reference(revision) -> dict:
    feature_ir = compile_feature_ir(revision.intent_graph)
    requirement_checks = [
        {
            "id": check.id,
            "status": check.status.value,
            "required_value": check.required_value,
            "measured_value": (
                _rounded(check.measured_value)
                if check.measured_value is not None else None
            ),
            "conflict_class": (
                check.conflict_class.value if check.conflict_class else None
            ),
        }
        for report in revision.measured
        for check in report.checks
        if check.stage.value == "requirement"
    ]
    graph_payload = revision.intent_graph.model_dump(mode="json")
    program_payload = revision.program.model_dump(mode="json")
    return {
        "revision": revision.revision,
        "parent_revision": revision.intent.parent_revision,
        "applied_proposal": revision.intent.applied_proposal,
        "approved_by": revision.intent.approved_by,
        "eig_sha256": _content_hash(graph_payload),
        "feature_ir": feature_ir_manifest(feature_ir).model_dump(mode="json"),
        "cad_program_sha256": _content_hash(program_payload),
        "cad_program": program_payload,
        "script_sha256": _sha256_bytes(revision.script.encode("utf-8")),
        "geometry": _geometry_fingerprint(revision.execution.shape),
        "requirement_checks": requirement_checks,
        "release": {
            "status": revision.decision.status.value,
            "step_export_allowed": revision.decision.step_export_allowed,
            "responsible_parameters": revision.decision.responsible_parameters,
        },
    }


def build_reference() -> dict:
    result = run(
        EXAMPLE / "sketch.png",
        EXAMPLE / "motor_datasheet.pdf",
        EXAMPLE / "requirement.txt",
        backend_override="fixture",
        create_messages=False,
    )
    result = repair(result, "widen_to_recommended", approved_by="r1-reference")
    v2 = result.latest

    with tempfile.TemporaryDirectory(prefix="spec2cad-r1-reference-") as directory:
        step_path = export_step(v2.execution, Path(directory) / "motor_adapter.step")
        round_trip_reports = verify_exported_step(
            step_path, v2.intent, v2.intent_graph
        )
        restored_fingerprint = _geometry_fingerprint(import_step(step_path))

    inputs = {}
    for name in ("sketch.png", "sketch.fixture.json", "motor_datasheet.pdf", "requirement.txt"):
        inputs[name] = _sha256_bytes((EXAMPLE / name).read_bytes())

    revisions = [_revision_reference(revision) for revision in result.revisions]
    return {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "case_id": "motor_adapter",
        "backend": "cadquery",
        "inputs_sha256": inputs,
        "revisions": revisions,
        "step_round_trip": {
            "revision": v2.revision,
            "all_reports_passed": all(report.passed for report in round_trip_reports),
            "geometry_matches_in_memory": (
                restored_fingerprint == revisions[-1]["geometry"]
            ),
            "restored_geometry": restored_fingerprint,
        },
    }


def canonical_json() -> str:
    return json.dumps(build_reference(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    print(canonical_json(), end="")
