"""Backend-protocol adapter for the isolated FreeCAD worker."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.schemas.cad_state_graph import CADStateGraph

from .contracts import (
    ArtifactKind,
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
from .freecad_worker import (
    FreeCADWorkerUnavailable,
    discover_freecad_cmd,
    run_freecad_worker,
)
from .freecad_worker_contracts import (
    FreeCADWorkerOperation,
    FreeCADWorkerRequest,
    WorkerStatus,
)
from .protocol import (
    AdapterDescriptor,
    BackendOperationResult,
    ExportRequest,
    InspectRequest,
    OperationStatus,
    ReimportVerificationRequest,
    unsupported_operation_result,
)


class FreeCADAdapter:
    def __init__(
        self,
        artifact_root: Path,
        *,
        executable: Path | None = None,
        timeout_seconds: float = 120.0,
    ):
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self._states = {}
        self._lock = RLock()
        try:
            self.executable = discover_freecad_cmd(executable)
            ping = run_freecad_worker(
                FreeCADWorkerRequest(
                    request_id="worker:adapter:ping",
                    operation=FreeCADWorkerOperation.PING,
                ),
                executable=self.executable,
                timeout_seconds=min(timeout_seconds, 30.0),
            )
            backend_version = ping.freecad_version or "unavailable"
        except FreeCADWorkerUnavailable:
            self.executable = None
            backend_version = "unavailable"
        self._descriptor = AdapterDescriptor(
            backend_id="freecad",
            backend_version=backend_version,
            adapter_version="1.0.0",
            supported_operations=(
                BackendOperation.BUILD,
                BackendOperation.INSPECT,
                BackendOperation.EXPORT_NATIVE,
                BackendOperation.EXPORT_NEUTRAL,
                BackendOperation.EXPORT_PREVIEW,
                BackendOperation.VERIFY_REIMPORT,
            ),
            native_media_types=("application/vnd.freecad",),
            neutral_media_types=("model/step",),
            preview_media_types=("model/stl",),
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def _diagnostic(
        self,
        request_id: str,
        operation: BackendOperation,
        code: BackendDiagnosticCode,
        message: str,
    ) -> BackendDiagnostic:
        return BackendDiagnostic(
            id=f"diag:freecad:{operation.value}:{request_id.replace(':', '_')}",
            severity=DiagnosticSeverity.ERROR,
            code=code,
            operation=operation,
            message=message,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        if request.backend_id != "freecad":
            return self._build_failure(
                request.request_id,
                BackendDiagnosticCode.INVALID_REQUEST,
                f"request targets {request.backend_id!r}, not 'freecad'",
            )
        if self.executable is None:
            return self._build_failure(
                request.request_id,
                BackendDiagnosticCode.BACKEND_UNAVAILABLE,
                "FreeCADCmd is unavailable",
            )
        response = run_freecad_worker(
            FreeCADWorkerRequest(
                request_id=f"worker:{request.request_id}",
                operation=FreeCADWorkerOperation.BUILD,
                build_request=request,
                artifact_root=str(self.artifact_root),
            ),
            executable=self.executable,
            timeout_seconds=self.timeout_seconds,
        )
        if response.status is not WorkerStatus.SUCCEEDED:
            unsupported = response.status is WorkerStatus.UNSUPPORTED
            message = "; ".join(item.message for item in response.diagnostics)
            return self._build_failure(
                request.request_id,
                (
                    BackendDiagnosticCode.UNSUPPORTED_CAPABILITY
                    if unsupported else BackendDiagnosticCode.BUILD_FAILED
                ),
                message or "FreeCAD worker failed",
                unsupported=unsupported,
            )
        return self._successful_build(request, response)

    def _successful_build(self, request: BuildRequest, response) -> BuildResult:
        graph = response.cad_state_graph
        graph_identity = csg_manifest(graph)
        snapshot = StateSnapshot(
            id=f"state:freecad:{request.feature_ir_manifest.content_sha256[:16]}",
            request_id=request.request_id,
            backend_id="freecad",
            backend_version=response.freecad_version,
            source_feature_ir_sha256=request.feature_ir_manifest.content_sha256,
            status=StateStatus.READY,
            recompute_state=RecomputeState.SUCCEEDED,
            native_document_id=response.native_build.document_path,
            state_graph_id=graph.id,
            state_graph_sha256=graph_identity.content_sha256,
        )
        with self._lock:
            self._states[snapshot.id] = (snapshot, response)
        return BuildResult(
            request_id=request.request_id,
            backend_id="freecad",
            backend_version=response.freecad_version,
            status=BuildStatus.SUCCEEDED,
            snapshot=snapshot,
            artifacts=response.artifacts,
        )

    def edit_parameter(
        self,
        source_snapshot: StateSnapshot,
        updated_request: BuildRequest,
        *,
        parameter_id: str,
        parameter_value: float,
    ) -> BuildResult:
        """Edit one native value through its stable Feature IR parameter ID."""
        if self.executable is None or not source_snapshot.native_document_id:
            return self._build_failure(
                updated_request.request_id,
                BackendDiagnosticCode.BACKEND_UNAVAILABLE,
                "FreeCAD native edit requires an available worker and native document",
            )
        response = run_freecad_worker(
            FreeCADWorkerRequest(
                request_id=f"worker:{updated_request.request_id}:edit",
                operation=FreeCADWorkerOperation.EDIT_PARAMETER,
                build_request=updated_request,
                artifact_root=str(self.artifact_root),
                native_document_path=source_snapshot.native_document_id,
                parameter_id=parameter_id,
                parameter_value=parameter_value,
            ),
            executable=self.executable,
            timeout_seconds=self.timeout_seconds,
        )
        if response.status is not WorkerStatus.SUCCEEDED:
            return self._build_failure(
                updated_request.request_id,
                BackendDiagnosticCode.RECOMPUTE_FAILED,
                "; ".join(item.message for item in response.diagnostics),
            )
        return self._successful_build(updated_request, response)

    def _build_failure(
        self,
        request_id: str,
        code: BackendDiagnosticCode,
        message: str,
        *,
        unsupported: bool = False,
    ) -> BuildResult:
        diagnostic = self._diagnostic(
            request_id, BackendOperation.BUILD, code, message
        )
        return BuildResult(
            request_id=request_id,
            backend_id="freecad",
            backend_version=self.descriptor.backend_version,
            status=BuildStatus.UNSUPPORTED if unsupported else BuildStatus.FAILED,
            diagnostics=(diagnostic,),
        )

    def inspect(self, request: InspectRequest) -> BackendOperationResult:
        with self._lock:
            known = request.snapshot.id in self._states
        if not known:
            return self._failed_operation(
                request.request_id, BackendOperation.INSPECT,
                BackendDiagnosticCode.INSPECTION_FAILED,
                f"unknown FreeCAD state {request.snapshot.id!r}",
            )
        return BackendOperationResult(
            request_id=request.request_id,
            backend_id="freecad",
            backend_version=request.snapshot.backend_version,
            operation=BackendOperation.INSPECT,
            status=OperationStatus.SUCCEEDED,
            snapshot=request.snapshot,
        )

    def _export_result(
        self,
        request: ExportRequest,
        operation: BackendOperation,
        kind: ArtifactKind,
    ) -> BackendOperationResult:
        with self._lock:
            state = self._states.get(request.snapshot.id)
        if state is None:
            return self._failed_operation(
                request.request_id, operation, BackendDiagnosticCode.EXPORT_FAILED,
                f"unknown FreeCAD state {request.snapshot.id!r}",
            )
        artifact = next(
            item for item in state[1].artifacts if item.kind is kind
        )
        return BackendOperationResult(
            request_id=request.request_id,
            backend_id="freecad",
            backend_version=request.snapshot.backend_version,
            operation=operation,
            status=OperationStatus.SUCCEEDED,
            artifact=artifact,
        )

    def export_native(self, request: ExportRequest) -> BackendOperationResult:
        return self._export_result(
            request, BackendOperation.EXPORT_NATIVE, ArtifactKind.NATIVE_MODEL
        )

    def export_neutral(self, request: ExportRequest) -> BackendOperationResult:
        return self._export_result(
            request, BackendOperation.EXPORT_NEUTRAL, ArtifactKind.NEUTRAL_MODEL
        )

    def export_preview(self, request: ExportRequest) -> BackendOperationResult:
        return self._export_result(
            request, BackendOperation.EXPORT_PREVIEW, ArtifactKind.PREVIEW_MODEL
        )

    def verify_reimport(
        self, request: ReimportVerificationRequest
    ) -> BackendOperationResult:
        if self.executable is None:
            return self._failed_operation(
                request.request_id, BackendOperation.VERIFY_REIMPORT,
                BackendDiagnosticCode.BACKEND_UNAVAILABLE,
                "FreeCADCmd is unavailable",
            )
        response = run_freecad_worker(
            FreeCADWorkerRequest(
                request_id=f"worker:{request.request_id}",
                operation=FreeCADWorkerOperation.VERIFY_REIMPORT,
                artifact=request.artifact,
                artifact_path=str((self.artifact_root / request.artifact.filename).resolve()),
            ),
            executable=self.executable,
            timeout_seconds=self.timeout_seconds,
        )
        if response.status is not WorkerStatus.SUCCEEDED:
            return self._failed_operation(
                request.request_id, BackendOperation.VERIFY_REIMPORT,
                BackendDiagnosticCode.REIMPORT_FAILED,
                "; ".join(item.message for item in response.diagnostics),
            )
        snapshot = StateSnapshot(
            id=f"state:freecad:reimport:{request.artifact.content_sha256[:16]}",
            request_id=request.request_id,
            backend_id="freecad",
            backend_version=response.freecad_version,
            source_feature_ir_sha256=request.expected_feature_ir_sha256,
            status=StateStatus.READY,
            recompute_state=RecomputeState.NOT_APPLICABLE,
            native_document_id=str(
                (self.artifact_root / request.artifact.filename).resolve()
            ),
        )
        return BackendOperationResult(
            request_id=request.request_id,
            backend_id="freecad",
            backend_version=response.freecad_version,
            operation=BackendOperation.VERIFY_REIMPORT,
            status=OperationStatus.SUCCEEDED,
            snapshot=snapshot,
            reimport_verified=True,
        )

    def _failed_operation(
        self,
        request_id: str,
        operation: BackendOperation,
        code: BackendDiagnosticCode,
        message: str,
    ) -> BackendOperationResult:
        return BackendOperationResult(
            request_id=request_id,
            backend_id="freecad",
            backend_version=self.descriptor.backend_version,
            operation=operation,
            status=OperationStatus.FAILED,
            diagnostics=(self._diagnostic(request_id, operation, code, message),),
        )

    def csg_for(self, snapshot: StateSnapshot) -> CADStateGraph:
        with self._lock:
            state = self._states.get(snapshot.id)
        if state is None:
            raise KeyError(f"unknown FreeCAD state {snapshot.id!r}")
        return state[1].cad_state_graph
