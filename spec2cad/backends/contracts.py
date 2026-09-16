"""Strict data contracts shared by every CAD backend.

These messages deliberately contain only serializable engineering data. Kernel
objects, Python callbacks and executable source cannot cross this boundary.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.feature_serialization import FeatureIRManifest, feature_ir_manifest
from spec2cad.schemas.feature_ir import FeatureIR


BACKEND_PROTOCOL_SCHEMA_VERSION = "1.0.0"
Sha256 = str


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BackendOperation(str, Enum):
    BUILD = "build"
    INSPECT = "inspect"
    EXPORT_NATIVE = "export_native"
    EXPORT_NEUTRAL = "export_neutral"
    EXPORT_PREVIEW = "export_preview"
    VERIFY_REIMPORT = "verify_reimport"


class ArtifactKind(str, Enum):
    NATIVE_MODEL = "native_model"
    NEUTRAL_MODEL = "neutral_model"
    PREVIEW_MODEL = "preview_model"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BackendDiagnosticCode(str, Enum):
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_REQUEST = "invalid_request"
    INVALID_FEATURE_IR = "invalid_feature_ir"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BUILD_FAILED = "build_failed"
    INSPECTION_FAILED = "inspection_failed"
    EXPORT_FAILED = "export_failed"
    REIMPORT_FAILED = "reimport_failed"
    RECOMPUTE_FAILED = "recompute_failed"


class BuildStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class StateStatus(str, Enum):
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class RecomputeState(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"


class BackendDiagnostic(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    severity: DiagnosticSeverity
    code: BackendDiagnosticCode
    operation: BackendOperation
    message: str = Field(min_length=1)
    feature_ir_record_id: str | None = None
    native_entity_id: str | None = None


class ArtifactManifest(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    kind: ArtifactKind
    filename: str = Field(min_length=1, pattern=r"^[^/\\]+$")
    media_type: str = Field(min_length=3, pattern=r"^[^/\s]+/[^/\s]+$")
    content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0)
    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    source_feature_ir_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")


class StateSnapshot(_Contract):
    """Identity and health of one immutable backend observation.

    The optional state-graph pair is populated once a backend can emit the CAD
    State Graph defined in R1.3. It is intentionally an identity, not an
    untyped placeholder for graph content.
    """

    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    request_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    source_feature_ir_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    status: StateStatus
    recompute_state: RecomputeState
    native_document_id: str | None = None
    state_graph_id: str | None = None
    state_graph_sha256: Sha256 | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    diagnostics: tuple[BackendDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_state_graph_identity(self) -> "StateSnapshot":
        if (self.state_graph_id is None) != (self.state_graph_sha256 is None):
            raise ValueError("state graph id and hash must be present together")
        if self.status is StateStatus.READY and any(
            item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics
        ):
            raise ValueError("ready snapshots cannot contain error diagnostics")
        if self.recompute_state is RecomputeState.FAILED and self.status is StateStatus.READY:
            raise ValueError("failed recompute cannot produce a ready snapshot")
        return self


class BuildRequest(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    request_id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    backend_id: str = Field(min_length=1)
    feature_ir: FeatureIR
    feature_ir_manifest: FeatureIRManifest
    requested_artifacts: tuple[ArtifactKind, ...] = ()
    inspect: bool = True
    verify_reimport: bool = False

    @model_validator(mode="after")
    def validate_request_identity(self) -> "BuildRequest":
        if self.feature_ir_manifest != feature_ir_manifest(self.feature_ir):
            raise ValueError("Feature IR manifest does not match the request payload")
        if len(set(self.requested_artifacts)) != len(self.requested_artifacts):
            raise ValueError("requested artifact kinds must be unique")
        if self.verify_reimport and ArtifactKind.NEUTRAL_MODEL not in self.requested_artifacts:
            raise ValueError("re-import verification requires a neutral model artifact")
        return self


class BuildResult(_Contract):
    schema_version: Literal["1.0.0"] = BACKEND_PROTOCOL_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    status: BuildStatus
    snapshot: StateSnapshot | None = None
    artifacts: tuple[ArtifactManifest, ...] = ()
    diagnostics: tuple[BackendDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> "BuildResult":
        errors = [
            item for item in (*self.diagnostics, *(self.snapshot.diagnostics if self.snapshot else ()))
            if item.severity is DiagnosticSeverity.ERROR
        ]
        if self.snapshot is not None:
            if self.snapshot.request_id != self.request_id:
                raise ValueError("snapshot request id does not match result")
            if self.snapshot.backend_id != self.backend_id:
                raise ValueError("snapshot backend id does not match result")
            if self.snapshot.backend_version != self.backend_version:
                raise ValueError("snapshot backend version does not match result")
        if any(item.backend_id != self.backend_id for item in self.artifacts):
            raise ValueError("artifact backend id does not match result")
        if any(item.backend_version != self.backend_version for item in self.artifacts):
            raise ValueError("artifact backend version does not match result")
        if self.snapshot is not None and any(
            item.source_feature_ir_sha256 != self.snapshot.source_feature_ir_sha256
            for item in self.artifacts
        ):
            raise ValueError("artifact Feature IR identity does not match snapshot")
        if len({item.id for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact ids must be unique")
        if len({item.kind for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact kinds must be unique")
        if self.status is BuildStatus.SUCCEEDED:
            if self.snapshot is None or self.snapshot.status is not StateStatus.READY:
                raise ValueError("successful builds require a ready snapshot")
            if errors:
                raise ValueError("successful builds cannot contain error diagnostics")
        elif not errors:
            raise ValueError("failed and unsupported builds require an error diagnostic")
        if self.status is BuildStatus.UNSUPPORTED and not any(
            item.code is BackendDiagnosticCode.UNSUPPORTED_CAPABILITY for item in errors
        ):
            raise ValueError("unsupported builds require an unsupported-capability diagnostic")
        return self
