"""Semantic operation surface implemented by every CAD backend adapter."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from .contracts import (
    BACKEND_PROTOCOL_SCHEMA_VERSION,
    ArtifactKind,
    ArtifactManifest,
    BackendDiagnostic,
    BackendDiagnosticCode,
    BackendOperation,
    BuildRequest,
    BuildResult,
    DiagnosticSeverity,
    Sha256,
    StateSnapshot,
    _Contract,
)


class AdapterDescriptor(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    supported_operations: tuple[BackendOperation, ...]
    native_media_types: tuple[str, ...] = ()
    neutral_media_types: tuple[str, ...] = ()
    preview_media_types: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_operations(self) -> "AdapterDescriptor":
        if len(set(self.supported_operations)) != len(self.supported_operations):
            raise ValueError("supported operations must be unique")
        if BackendOperation.BUILD not in self.supported_operations:
            raise ValueError("every backend adapter must support build")
        return self

    def supports(self, operation: BackendOperation) -> bool:
        return operation in self.supported_operations


class InspectRequest(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    snapshot: StateSnapshot


class ExportRequest(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    snapshot: StateSnapshot


class ReimportVerificationRequest(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    artifact: ArtifactManifest
    expected_feature_ir_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_neutral_artifact(self) -> "ReimportVerificationRequest":
        if self.artifact.kind is not ArtifactKind.NEUTRAL_MODEL:
            raise ValueError("only neutral model artifacts can be re-import verified")
        if self.artifact.source_feature_ir_sha256 != self.expected_feature_ir_sha256:
            raise ValueError("artifact and expected Feature IR identities differ")
        return self


class OperationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class BackendOperationResult(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    operation: BackendOperation
    status: OperationStatus
    snapshot: StateSnapshot | None = None
    artifact: ArtifactManifest | None = None
    reimport_verified: bool | None = None
    diagnostics: tuple[BackendDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_operation_result(self) -> "BackendOperationResult":
        errors = [
            item for item in self.diagnostics
            if item.severity is DiagnosticSeverity.ERROR
        ]
        if any(item.operation is not self.operation for item in self.diagnostics):
            raise ValueError("diagnostic operation does not match result operation")
        if self.snapshot is not None and self.snapshot.backend_id != self.backend_id:
            raise ValueError("snapshot backend does not match operation result")
        if self.artifact is not None and self.artifact.backend_id != self.backend_id:
            raise ValueError("artifact backend does not match operation result")
        if self.status == OperationStatus.SUCCEEDED:
            if errors:
                raise ValueError("successful operations cannot contain error diagnostics")
            if self.operation is BackendOperation.INSPECT and self.snapshot is None:
                raise ValueError("successful inspection requires a snapshot")
            expected_kind = {
                BackendOperation.EXPORT_NATIVE: ArtifactKind.NATIVE_MODEL,
                BackendOperation.EXPORT_NEUTRAL: ArtifactKind.NEUTRAL_MODEL,
                BackendOperation.EXPORT_PREVIEW: ArtifactKind.PREVIEW_MODEL,
            }.get(self.operation)
            if expected_kind is not None and (
                self.artifact is None or self.artifact.kind is not expected_kind
            ):
                raise ValueError(f"successful {self.operation.value} requires {expected_kind.value}")
            if (
                self.operation is BackendOperation.VERIFY_REIMPORT
                and (self.snapshot is None or self.reimport_verified is not True)
            ):
                raise ValueError("successful re-import requires a verified snapshot")
        else:
            if not errors:
                raise ValueError("failed and unsupported operations require an error diagnostic")
            if self.status == OperationStatus.UNSUPPORTED and not any(
                item.code is BackendDiagnosticCode.UNSUPPORTED_CAPABILITY for item in errors
            ):
                raise ValueError("unsupported operations require an unsupported-capability diagnostic")
        return self


def unsupported_operation_result(
    descriptor: AdapterDescriptor,
    request_id: str,
    operation: BackendOperation,
    message: str | None = None,
) -> BackendOperationResult:
    """Create the one fail-closed representation of an unsupported operation."""
    diagnostic = BackendDiagnostic(
        id=f"diag:{descriptor.backend_id}:{operation.value}:unsupported",
        severity=DiagnosticSeverity.ERROR,
        code=BackendDiagnosticCode.UNSUPPORTED_CAPABILITY,
        operation=operation,
        message=message or f"{descriptor.backend_id} does not support {operation.value}",
    )
    return BackendOperationResult(
        request_id=request_id,
        backend_id=descriptor.backend_id,
        backend_version=descriptor.backend_version,
        operation=operation,
        status=OperationStatus.UNSUPPORTED,
        diagnostics=(diagnostic,),
    )


@runtime_checkable
class CADBackend(Protocol):
    """Backend adapters expose operations, never their native kernel objects."""

    @property
    def descriptor(self) -> AdapterDescriptor: ...

    def build(self, request: BuildRequest) -> BuildResult: ...

    def inspect(self, request: InspectRequest) -> BackendOperationResult: ...

    def export_native(self, request: ExportRequest) -> BackendOperationResult: ...

    def export_neutral(self, request: ExportRequest) -> BackendOperationResult: ...

    def export_preview(self, request: ExportRequest) -> BackendOperationResult: ...

    def verify_reimport(
        self, request: ReimportVerificationRequest
    ) -> BackendOperationResult: ...
