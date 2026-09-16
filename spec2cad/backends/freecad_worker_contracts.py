"""Typed host-side envelope for the isolated FreeCAD worker process."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import ArtifactKind, ArtifactManifest, BuildRequest
from spec2cad.schemas.cad_state_graph import CADStateGraph


FREECAD_WORKER_SCHEMA_VERSION = "1.0.0"


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FreeCADWorkerOperation(str, Enum):
    PING = "ping"
    BUILD = "build"
    EDIT_PARAMETER = "edit_parameter"
    VERIFY_REIMPORT = "verify_reimport"


class WorkerStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class FreeCADWorkerRequest(_Message):
    schema_version: Literal["1.0.0"] = FREECAD_WORKER_SCHEMA_VERSION
    request_id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    operation: FreeCADWorkerOperation
    build_request: BuildRequest | None = None
    artifact_root: str | None = None
    native_document_path: str | None = None
    parameter_id: str | None = None
    parameter_value: float | None = Field(default=None, allow_inf_nan=False)
    artifact: ArtifactManifest | None = None
    artifact_path: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "FreeCADWorkerRequest":
        building = self.operation in {
            FreeCADWorkerOperation.BUILD, FreeCADWorkerOperation.EDIT_PARAMETER,
        }
        editing = self.operation is FreeCADWorkerOperation.EDIT_PARAMETER
        reimporting = self.operation is FreeCADWorkerOperation.VERIFY_REIMPORT
        build_fields = (self.build_request, self.artifact_root)
        if building != all(item is not None for item in build_fields) or (
            not building and any(item is not None for item in build_fields)
        ):
            raise ValueError("build/edit operation requires build_request and artifact_root")
        edit_fields = (
            self.native_document_path, self.parameter_id, self.parameter_value,
        )
        if editing != all(item is not None for item in edit_fields) or (
            not editing and any(item is not None for item in edit_fields)
        ):
            raise ValueError(
                "edit operation requires native document, Feature IR parameter ID and value"
            )
        reimport_fields = (self.artifact, self.artifact_path)
        if reimporting != all(item is not None for item in reimport_fields) or (
            not reimporting and any(item is not None for item in reimport_fields)
        ):
            raise ValueError("re-import operation requires one artifact and absolute path")
        if building:
            if self.build_request.backend_id != "freecad":
                raise ValueError("FreeCAD worker build must target the freecad backend")
            if not Path(self.artifact_root).is_absolute():
                raise ValueError("artifact_root must be absolute")
        if editing and not Path(self.native_document_path).is_absolute():
            raise ValueError("native_document_path must be absolute")
        if reimporting and self.artifact.kind is not ArtifactKind.NEUTRAL_MODEL:
            raise ValueError("re-import requires a neutral model artifact")
        if reimporting and not Path(self.artifact_path).is_absolute():
            raise ValueError("re-import artifact_path must be absolute")
        return self


class FreeCADWorkerDiagnostic(_Message):
    code: Literal[
        "invalid_request",
        "protocol_mismatch",
        "unsupported_capability",
        "worker_failure",
        "timeout",
        "malformed_response",
        "invalid_feature_ir",
        "build_failed",
    ]
    message: str = Field(min_length=1)


class FreeCADSketchSummary(_Message):
    name: str = Field(min_length=1)
    fully_constrained: bool
    degrees_of_freedom: int = Field(ge=0)
    geometry_count: int = Field(ge=1)
    constraint_count: int = Field(ge=1)


class FreeCADFeatureSummary(_Message):
    name: str = Field(min_length=1)
    type_id: str = Field(min_length=1)


class FreeCADNativeBuildSummary(_Message):
    document_path: str = Field(min_length=1)
    document_name: str = Field(min_length=1)
    body_name: str = Field(min_length=1)
    parameter_names: tuple[str, ...] = Field(min_length=1)
    sketches: tuple[FreeCADSketchSummary, ...] = Field(min_length=1)
    features: tuple[FreeCADFeatureSummary, ...] = Field(min_length=1)
    recompute_errors: tuple[str, ...] = ()
    solid_count: int = Field(ge=0)
    volume_mm3: float = Field(ge=0, allow_inf_nan=False)


class FreeCADWorkerResponse(_Message):
    schema_version: Literal["1.0.0"] = FREECAD_WORKER_SCHEMA_VERSION
    request_id: str = Field(min_length=1)
    operation: FreeCADWorkerOperation
    status: WorkerStatus
    freecad_version: str | None = None
    native_build: FreeCADNativeBuildSummary | None = None
    cad_state_graph: CADStateGraph | None = None
    artifacts: tuple[ArtifactManifest, ...] = ()
    reimport_verified: bool | None = None
    diagnostics: tuple[FreeCADWorkerDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> "FreeCADWorkerResponse":
        if self.status is WorkerStatus.SUCCEEDED:
            if self.diagnostics:
                raise ValueError("successful worker response cannot have diagnostics")
            if self.operation is FreeCADWorkerOperation.PING and not self.freecad_version:
                raise ValueError("successful ping requires FreeCAD version")
            if self.operation in {
                FreeCADWorkerOperation.BUILD, FreeCADWorkerOperation.EDIT_PARAMETER,
            } and (
                self.native_build is None or self.cad_state_graph is None
            ):
                raise ValueError("successful build/edit requires native build summary and CSG")
            if self.operation in {
                FreeCADWorkerOperation.BUILD, FreeCADWorkerOperation.EDIT_PARAMETER,
            } and {
                item.kind for item in self.artifacts
            } != {
                ArtifactKind.NATIVE_MODEL,
                ArtifactKind.NEUTRAL_MODEL,
                ArtifactKind.PREVIEW_MODEL,
            }:
                raise ValueError("successful build/edit requires all three artifacts")
            if (
                self.operation is FreeCADWorkerOperation.VERIFY_REIMPORT
                and self.reimport_verified is not True
            ):
                raise ValueError("successful re-import must be verified")
        elif not self.diagnostics:
            raise ValueError("failed or unsupported worker response requires diagnostics")
        return self
