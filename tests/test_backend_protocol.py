"""Every backend exposes the same explicit semantic operation boundary."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.backends import (
    AdapterDescriptor,
    ArtifactKind,
    ArtifactManifest,
    BackendOperation,
    BackendOperationResult,
    BuildRequest,
    BuildResult,
    BuildStatus,
    CADBackend,
    ExportRequest,
    InspectRequest,
    OperationStatus,
    RecomputeState,
    ReimportVerificationRequest,
    StateSnapshot,
    StateStatus,
    unsupported_operation_result,
)
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import run


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


class BuildOnlyBackend:
    descriptor = AdapterDescriptor(
        backend_id="build_only",
        backend_version="1.0",
        adapter_version="1.0.0",
        supported_operations=(BackendOperation.BUILD,),
    )

    def build(self, request: BuildRequest) -> BuildResult:
        unsupported = unsupported_operation_result(
            self.descriptor, request.request_id, BackendOperation.BUILD,
            "the fixture advertises the operation but intentionally refuses this document",
        )
        return BuildResult(
            request_id=request.request_id,
            backend_id=self.descriptor.backend_id,
            backend_version=self.descriptor.backend_version,
            status=BuildStatus.UNSUPPORTED,
            diagnostics=unsupported.diagnostics,
        )

    def inspect(self, request: InspectRequest) -> BackendOperationResult:
        return unsupported_operation_result(
            self.descriptor, request.request_id, BackendOperation.INSPECT
        )

    def export_native(self, request: ExportRequest) -> BackendOperationResult:
        return unsupported_operation_result(
            self.descriptor, request.request_id, BackendOperation.EXPORT_NATIVE
        )

    def export_neutral(self, request: ExportRequest) -> BackendOperationResult:
        return unsupported_operation_result(
            self.descriptor, request.request_id, BackendOperation.EXPORT_NEUTRAL
        )

    def export_preview(self, request: ExportRequest) -> BackendOperationResult:
        return unsupported_operation_result(
            self.descriptor, request.request_id, BackendOperation.EXPORT_PREVIEW
        )

    def verify_reimport(
        self, request: ReimportVerificationRequest
    ) -> BackendOperationResult:
        return unsupported_operation_result(
            self.descriptor, request.request_id, BackendOperation.VERIFY_REIMPORT
        )


def test_runtime_protocol_has_every_required_operation_and_typed_refusal():
    backend = BuildOnlyBackend()
    assert isinstance(backend, CADBackend)
    assert {name for name in (
        "build", "inspect", "export_native", "export_neutral",
        "export_preview", "verify_reimport",
    ) if callable(getattr(backend, name))} == {
        "build", "inspect", "export_native", "export_neutral",
        "export_preview", "verify_reimport",
    }
    snapshot = StateSnapshot(
        id="state:fixture",
        request_id="build:fixture",
        backend_id="build_only",
        backend_version="1.0",
        source_feature_ir_sha256="a" * 64,
        status=StateStatus.READY,
        recompute_state=RecomputeState.NOT_APPLICABLE,
    )
    result = backend.export_preview(
        ExportRequest(request_id="export:preview", snapshot=snapshot)
    )
    assert result.status is OperationStatus.UNSUPPORTED
    assert result.diagnostics[0].operation is BackendOperation.EXPORT_PREVIEW


def test_descriptor_declares_unique_capabilities_and_build_is_mandatory():
    with pytest.raises(ValidationError, match="must support build"):
        AdapterDescriptor(
            backend_id="bad",
            backend_version="1",
            adapter_version="1",
            supported_operations=(BackendOperation.INSPECT,),
        )
    with pytest.raises(ValidationError, match="must be unique"):
        AdapterDescriptor(
            backend_id="bad",
            backend_version="1",
            adapter_version="1",
            supported_operations=(BackendOperation.BUILD, BackendOperation.BUILD),
        )


def test_reimport_request_accepts_only_matching_neutral_artifact():
    document = compile_feature_ir(run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    ).latest.intent_graph)
    manifest = feature_ir_manifest(document)
    build_request = BuildRequest(
        request_id="build:motor",
        backend_id="build_only",
        feature_ir=document,
        feature_ir_manifest=manifest,
        requested_artifacts=(ArtifactKind.NEUTRAL_MODEL,),
    )
    artifact = ArtifactManifest(
        id="artifact:motor:step",
        kind=ArtifactKind.NEUTRAL_MODEL,
        filename="motor.step",
        media_type="model/step",
        content_sha256="b" * 64,
        byte_length=100,
        backend_id="build_only",
        backend_version="1.0",
        source_feature_ir_sha256=manifest.content_sha256,
    )
    request = ReimportVerificationRequest(
        request_id="reimport:motor",
        artifact=artifact,
        expected_feature_ir_sha256=manifest.content_sha256,
    )
    assert build_request.request_id == "build:motor"
    assert request.artifact.kind is ArtifactKind.NEUTRAL_MODEL
    assert BuildOnlyBackend().verify_reimport(request).status is OperationStatus.UNSUPPORTED
