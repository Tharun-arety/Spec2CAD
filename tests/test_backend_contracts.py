"""Backend messages are strict, portable and internally consistent."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.backends import (
    ArtifactKind,
    ArtifactManifest,
    BackendDiagnostic,
    BackendDiagnosticCode,
    BackendOperation,
    BuildRequest,
    BuildResult,
    BuildStatus,
    DiagnosticSeverity,
    RecomputeState,
    StateSnapshot,
    StateStatus,
)
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import run


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
HASH = "a" * 64


@pytest.fixture(scope="module")
def motor_feature_ir():
    result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    return compile_feature_ir(result.latest.intent_graph)


def request_for(document, **changes):
    values = {
        "request_id": "build:motor:r1",
        "backend_id": "cadquery",
        "feature_ir": document,
        "feature_ir_manifest": feature_ir_manifest(document),
        "requested_artifacts": (
            ArtifactKind.NEUTRAL_MODEL,
            ArtifactKind.PREVIEW_MODEL,
        ),
        "verify_reimport": True,
    }
    values.update(changes)
    return BuildRequest(**values)


def test_real_feature_ir_request_is_deterministic_and_json_portable(motor_feature_ir):
    request = request_for(motor_feature_ir)
    restored = BuildRequest.model_validate_json(request.model_dump_json())
    assert restored == request
    assert restored.feature_ir_manifest.content_sha256 == feature_ir_manifest(
        motor_feature_ir
    ).content_sha256
    assert "cadquery" not in restored.feature_ir.model_dump_json().lower()


def test_request_refuses_manifest_mismatch_duplicate_artifacts_and_bad_reimport(
    motor_feature_ir,
):
    manifest = feature_ir_manifest(motor_feature_ir).model_copy(
        update={"content_sha256": HASH}
    )
    with pytest.raises(ValidationError, match="manifest does not match"):
        request_for(motor_feature_ir, feature_ir_manifest=manifest)
    with pytest.raises(ValidationError, match="must be unique"):
        request_for(
            motor_feature_ir,
            requested_artifacts=(ArtifactKind.NEUTRAL_MODEL,) * 2,
        )
    with pytest.raises(ValidationError, match="requires a neutral"):
        request_for(
            motor_feature_ir,
            requested_artifacts=(ArtifactKind.PREVIEW_MODEL,),
        )


def diagnostic(code=BackendDiagnosticCode.BUILD_FAILED):
    return BackendDiagnostic(
        id="diag:build",
        severity=DiagnosticSeverity.ERROR,
        code=code,
        operation=BackendOperation.BUILD,
        message="bounded failure",
    )


def ready_snapshot():
    return StateSnapshot(
        id="state:motor:r1",
        request_id="build:motor:r1",
        backend_id="cadquery",
        backend_version="2.6.1",
        source_feature_ir_sha256=HASH,
        status=StateStatus.READY,
        recompute_state=RecomputeState.NOT_APPLICABLE,
    )


def neutral_artifact():
    return ArtifactManifest(
        id="artifact:motor:step",
        kind=ArtifactKind.NEUTRAL_MODEL,
        filename="motor.step",
        media_type="model/step",
        content_sha256="b" * 64,
        byte_length=1234,
        backend_id="cadquery",
        backend_version="2.6.1",
        source_feature_ir_sha256=HASH,
    )


def test_success_result_requires_ready_error_free_snapshot():
    result = BuildResult(
        request_id="build:motor:r1",
        backend_id="cadquery",
        backend_version="2.6.1",
        status=BuildStatus.SUCCEEDED,
        snapshot=ready_snapshot(),
        artifacts=(neutral_artifact(),),
    )
    assert BuildResult.model_validate_json(result.model_dump_json()) == result

    with pytest.raises(ValidationError, match="require a ready snapshot"):
        BuildResult.model_validate({**result.model_dump(), "snapshot": None})


def test_failure_and_unsupported_results_require_typed_error_diagnostics():
    with pytest.raises(ValidationError, match="require an error diagnostic"):
        BuildResult(
            request_id="build:motor:r1",
            backend_id="cadquery",
            backend_version="2.6.1",
            status=BuildStatus.FAILED,
        )
    with pytest.raises(ValidationError, match="unsupported-capability"):
        BuildResult(
            request_id="build:motor:r1",
            backend_id="cadquery",
            backend_version="2.6.1",
            status=BuildStatus.UNSUPPORTED,
            diagnostics=(diagnostic(),),
        )
    result = BuildResult(
        request_id="build:motor:r1",
        backend_id="cadquery",
        backend_version="2.6.1",
        status=BuildStatus.UNSUPPORTED,
        diagnostics=(diagnostic(BackendDiagnosticCode.UNSUPPORTED_CAPABILITY),),
    )
    assert result.status is BuildStatus.UNSUPPORTED


def test_contracts_forbid_extra_fields_bad_hashes_and_partial_graph_identity():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BackendDiagnostic(
            id="diag:bad",
            severity="error",
            code="build_failed",
            operation="build",
            message="bad",
            traceback="native internals must not leak",
        )
    with pytest.raises(ValidationError, match="String should match pattern"):
        ArtifactManifest.model_validate({
            **neutral_artifact().model_dump(), "content_sha256": "not-a-hash"
        })
    with pytest.raises(ValidationError, match="present together"):
        StateSnapshot(
            **ready_snapshot().model_dump(exclude={"state_graph_id", "state_graph_sha256"}),
            state_graph_id="csg:motor:r1",
        )
