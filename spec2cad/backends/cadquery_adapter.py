"""CadQuery implementation of the backend protocol.

`CADProgram` and the existing executor are retained as private adapter details
during the R1 migration. No caller supplies kernel selectors or executable code.
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import RLock

from spec2cad.cad.executor import (
    ExecutionError,
    ExecutionResult,
    execute,
    export_step,
    export_stl,
    import_step,
)
from spec2cad.cad.feature_ir_lowering import (
    FeatureIRLoweringError,
    lower_feature_ir_to_cad_program,
)
from spec2cad.schemas.cad_ir import CADProgram
from spec2cad.schemas.cad_state_graph import CADStateGraph
from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.validation import measure as M

from .contracts import (
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
from .protocol import (
    AdapterDescriptor,
    BackendOperationResult,
    ExportRequest,
    InspectRequest,
    OperationStatus,
    ReimportVerificationRequest,
    unsupported_operation_result,
)


def _cadquery_version() -> str:
    try:
        return version("cadquery")
    except PackageNotFoundError:  # pragma: no cover - import would already fail
        return "unknown"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _semantic_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _cadquery_csg(
    request: BuildRequest,
    execution: ExecutionResult,
    backend_version: str,
) -> CADStateGraph:
    """Observe only concepts CadQuery actually exposes for this build."""
    shape = execution.shape
    bounds = shape.BoundingBox()
    width = float(bounds.xlen)
    height = float(bounds.ylen)
    thickness = float(bounds.zlen)
    nodes: list[dict] = [
        {
            "kind": "document", "id": "document.cadquery_build",
            "label": "CadQuery build state", "backend_native_id": None,
            "native_format": None, "editable": False,
            "recompute": "not_applicable", "body_ids": ["body.main"],
        },
        {
            "kind": "body", "id": "body.main",
            "label": request.feature_ir.part.label,
            "backend_native_id": "result.solid",
            "feature_ids": [], "solid_count": len(shape.Solids()),
            "measurements": [
                {"name": "volume", "value": float(shape.Volume()), "unit": "mm3"}
            ],
        },
        {
            "kind": "diagnostic", "id": "diagnostic.kernel_build",
            "label": "Kernel build status", "backend_native_id": None,
            "severity": "info", "code": "build_ok",
            "message": "CadQuery produced one valid solid",
            "related_node_ids": ["body.main"],
        },
    ]
    unavailable = (
        ("editable_document", "absent", ()),
        ("parametric_sketch", "unsupported", tuple(
            item.id for item in request.feature_ir.features if item.type == "sketch"
        )),
        ("sketch_constraint", "unsupported", tuple(
            item.id for item in request.feature_ir.features if item.type == "sketch"
        )),
        ("parameter_expression", "unsupported", tuple(
            item.id for item in request.feature_ir.parameters
        )),
        ("native_feature", "unsupported", tuple(
            item.id for item in request.feature_ir.features if item.type != "sketch"
        )),
        ("native_export", "absent", ()),
    )
    for concept, status, feature_ids in unavailable:
        nodes.append({
            "kind": "unavailable_concept",
            "id": f"unavailable.{concept}",
            "label": concept.replace("_", " ").title(),
            "backend_native_id": None,
            "concept": concept,
            "status": status,
            "reason": (
                "CadQuery does not have this native editable concept; the adapter "
                "records B-Rep observations without fabricating one."
            ),
            "requested_feature_ir_ids": feature_ids,
        })

    solid_signature = {
        "width": width, "height": height,
        "thickness": thickness, "volume": float(shape.Volume()),
    }
    nodes.append({
        "kind": "semantic_topology",
        "id": "topology.part_solid", "label": "Final part solid",
        "backend_native_id": "semantic:part_solid",
        "topology_kind": "solid", "semantic_role": "part_solid",
        "geometry_type": "brep_solid",
        "signature_sha256": _semantic_hash(solid_signature),
        "centroid_mm": [
            float(shape.Center().x), float(shape.Center().y), float(shape.Center().z)
        ],
        "direction": None, "adjacent_topology_ids": [],
        "measurements": [
            {"name": "width", "value": width, "unit": "mm"},
            {"name": "height", "value": height, "unit": "mm"},
            {"name": "thickness", "value": thickness, "unit": "mm"},
            {"name": "volume", "value": float(shape.Volume()), "unit": "mm3"},
        ],
    })
    openings = sorted(
        M.circular_features(M.top_face(shape)),
        key=lambda item: (-item.radius, item.x, item.y),
    )
    topology_ids = ["topology.part_solid"]
    for opening in openings:
        signature = {
            "radius": opening.radius, "x": opening.x, "y": opening.y,
            "axis": [0.0, 0.0, 1.0],
        }
        token = _semantic_hash(signature)[:16]
        role = f"cylindrical_surface_{token}"
        topology_id = f"topology.cylinder_{token}"
        topology_ids.append(topology_id)
        nodes.append({
            "kind": "semantic_topology", "id": topology_id,
            "label": role.replace("_", " ").title(),
            "backend_native_id": f"semantic:{role}",
            "topology_kind": "face", "semantic_role": role,
            "geometry_type": "cylinder",
            "signature_sha256": _semantic_hash(signature),
            "centroid_mm": [opening.x, opening.y, 0.0],
            "direction": [0.0, 0.0, 1.0],
            "adjacent_topology_ids": ["topology.part_solid"],
            "measurements": [
                {"name": "diameter", "value": opening.diameter, "unit": "mm"},
                {"name": "center_x", "value": opening.x, "unit": "mm"},
                {"name": "center_y", "value": opening.y, "unit": "mm"},
            ],
        })

    relationships = []
    document_source = {
        "namespace": "cad_state_graph", "id": "document.cadquery_build"
    }
    relationships.append({
        "id": "rel.document.feature_ir_part", "kind": "realizes_feature_ir",
        "source": document_source,
        "target": {"namespace": "feature_ir", "id": request.feature_ir.part.id},
    })
    for link in request.feature_ir.part.intent_links:
        relationships.append({
            "id": f"rel.document.intent.{_safe_stem(link.eig_node_id).lower()}",
            "kind": "realizes_intent", "source": document_source,
            "target": {
                "namespace": "engineering_intent_graph", "id": link.eig_node_id
            },
        })
    source = {"namespace": "cad_state_graph", "id": "body.main"}
    relationships.append({
        "id": "rel.body.feature_ir_part", "kind": "realizes_feature_ir",
        "source": source,
        "target": {"namespace": "feature_ir", "id": request.feature_ir.part.id},
    })
    for link in request.feature_ir.part.intent_links:
        relationships.append({
            "id": f"rel.body.intent.{_safe_stem(link.eig_node_id).lower()}",
            "kind": "realizes_intent", "source": source,
            "target": {
                "namespace": "engineering_intent_graph", "id": link.eig_node_id
            },
        })
    parameters_by_id = {
        item.id: item for item in request.feature_ir.parameters
    }
    topology_by_id = {
        item["id"]: item for item in nodes
        if item["kind"] == "semantic_topology"
    }
    for interface in request.feature_ir.interfaces:
        if interface.correspondence_version is None:
            continue
        eig_interface_id = next(
            link.eig_node_id for link in interface.intent_links
            if link.relation.value == "corresponds_to"
        )
        for binding in interface.geometry_bindings:
            diameters = [
                parameters_by_id[parameter_id].value
                for parameter_id in binding.parameter_ids
                if parameter_id in parameters_by_id
                and "diameter" in parameters_by_id[parameter_id].name
            ]
            matching_topologies = []
            for topology_id, topology in topology_by_id.items():
                measured = {
                    item["name"]: item["value"]
                    for item in topology.get("measurements", [])
                }
                if topology.get("geometry_type") == "cylinder" and any(
                    abs(measured.get("diameter", float("inf")) - expected) <= 1e-6
                    for expected in diameters
                ):
                    matching_topologies.append(topology_id)
            for topology_id in matching_topologies:
                relationship_stem = (
                    f"rel.{topology_id.replace('.', '_')}.interface.{binding.role}"
                )
                for namespace, target_id, suffix in (
                    ("feature_ir", interface.id, "feature_ir"),
                    (
                        "engineering_intent_graph", eig_interface_id,
                        "engineering_intent_graph",
                    ),
                ):
                    relationships.append({
                        "id": f"{relationship_stem}.{suffix}",
                        "kind": "corresponds_to_interface",
                        "source": {
                            "namespace": "cad_state_graph", "id": topology_id
                        },
                        "target": {"namespace": namespace, "id": target_id},
                        "role": binding.role,
                    })
    return CADStateGraph(
        interface_correspondence_version=(
            "1.0.0" if any(
                item.correspondence_version is not None
                for item in request.feature_ir.interfaces
            ) else None
        ),
        id=(
            f"csg.cadquery.{_safe_stem(request.feature_ir.part.name).lower()}."
            f"r{request.feature_ir.design_revision}"
        ),
        build_request_id=request.request_id,
        backend_id="cadquery",
        backend_version=backend_version,
        source_feature_ir_sha256=request.feature_ir_manifest.content_sha256,
        root_document_id="document.cadquery_build",
        nodes=tuple(nodes),
        relationships=tuple(relationships),
    )


class CadQueryAdapter:
    """In-process kernel adapter with typed external state and diagnostics."""

    def __init__(self, artifact_root: Path | None = None):
        self.artifact_root = Path(artifact_root) if artifact_root is not None else None
        self._executions: dict[str, ExecutionResult] = {}
        self._imported_shapes: dict[str, object] = {}
        self._csgs: dict[str, CADStateGraph] = {}
        self._artifact_paths: dict[str, Path] = {}
        self._lock = RLock()
        self._descriptor = AdapterDescriptor(
            backend_id="cadquery",
            backend_version=_cadquery_version(),
            adapter_version="1.0.0",
            supported_operations=(
                BackendOperation.BUILD,
                BackendOperation.INSPECT,
                BackendOperation.EXPORT_NEUTRAL,
                BackendOperation.EXPORT_PREVIEW,
                BackendOperation.VERIFY_REIMPORT,
            ),
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
            id=f"diag:cadquery:{operation.value}:{_safe_stem(request_id)}",
            severity=DiagnosticSeverity.ERROR,
            code=code,
            operation=operation,
            message=message,
        )

    def _snapshot(
        self,
        request_id: str,
        source_hash: str,
        *,
        suffix: str = "build",
        csg: CADStateGraph | None = None,
    ) -> StateSnapshot:
        return StateSnapshot(
            id=f"state:cadquery:{source_hash[:16]}:{suffix}",
            request_id=request_id,
            backend_id=self.descriptor.backend_id,
            backend_version=self.descriptor.backend_version,
            source_feature_ir_sha256=source_hash,
            status=StateStatus.READY,
            recompute_state=RecomputeState.NOT_APPLICABLE,
            native_document_id=f"cadquery:{source_hash[:16]}",
            state_graph_id=csg.id if csg is not None else None,
            state_graph_sha256=(
                csg_manifest(csg).content_sha256 if csg is not None else None
            ),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        if request.backend_id != self.descriptor.backend_id:
            diagnostic = self._diagnostic(
                request.request_id,
                BackendOperation.BUILD,
                BackendDiagnosticCode.INVALID_REQUEST,
                f"request targets {request.backend_id!r}, not 'cadquery'",
            )
            return BuildResult(
                request_id=request.request_id,
                backend_id=self.descriptor.backend_id,
                backend_version=self.descriptor.backend_version,
                status=BuildStatus.FAILED,
                diagnostics=(diagnostic,),
            )
        try:
            program = lower_feature_ir_to_cad_program(request.feature_ir)
            values = {item.name: item.value for item in request.feature_ir.parameters}
            execution = execute(program, values)
        except FeatureIRLoweringError as exc:
            diagnostic = self._diagnostic(
                request.request_id,
                BackendOperation.BUILD,
                BackendDiagnosticCode.UNSUPPORTED_CAPABILITY,
                str(exc),
            )
            return BuildResult(
                request_id=request.request_id,
                backend_id=self.descriptor.backend_id,
                backend_version=self.descriptor.backend_version,
                status=BuildStatus.UNSUPPORTED,
                diagnostics=(diagnostic,),
            )
        except (ExecutionError, ValueError) as exc:
            diagnostic = self._diagnostic(
                request.request_id,
                BackendOperation.BUILD,
                BackendDiagnosticCode.BUILD_FAILED,
                f"{type(exc).__name__}: {exc}",
            )
            return BuildResult(
                request_id=request.request_id,
                backend_id=self.descriptor.backend_id,
                backend_version=self.descriptor.backend_version,
                status=BuildStatus.FAILED,
                diagnostics=(diagnostic,),
            )

        csg = _cadquery_csg(request, execution, self.descriptor.backend_version)
        snapshot = self._snapshot(
            request.request_id, request.feature_ir_manifest.content_sha256, csg=csg
        )
        with self._lock:
            self._executions[snapshot.id] = execution
            self._csgs[snapshot.id] = csg

        artifacts: list[ArtifactManifest] = []
        diagnostics: list[BackendDiagnostic] = []
        for kind, operation, method in (
            (ArtifactKind.NATIVE_MODEL, BackendOperation.EXPORT_NATIVE, self.export_native),
            (ArtifactKind.NEUTRAL_MODEL, BackendOperation.EXPORT_NEUTRAL, self.export_neutral),
            (ArtifactKind.PREVIEW_MODEL, BackendOperation.EXPORT_PREVIEW, self.export_preview),
        ):
            if kind not in request.requested_artifacts:
                continue
            export_result = method(ExportRequest(
                request_id=f"{request.request_id}:{operation.value}",
                snapshot=snapshot,
            ))
            if export_result.artifact is not None:
                artifacts.append(export_result.artifact)
            diagnostics.extend(export_result.diagnostics)

        if diagnostics:
            status = (
                BuildStatus.UNSUPPORTED
                if any(item.code is BackendDiagnosticCode.UNSUPPORTED_CAPABILITY for item in diagnostics)
                else BuildStatus.FAILED
            )
        else:
            status = BuildStatus.SUCCEEDED
        return BuildResult(
            request_id=request.request_id,
            backend_id=self.descriptor.backend_id,
            backend_version=self.descriptor.backend_version,
            status=status,
            snapshot=snapshot,
            artifacts=tuple(artifacts),
            diagnostics=tuple(diagnostics),
        )

    def inspect(self, request: InspectRequest) -> BackendOperationResult:
        with self._lock:
            known = (
                request.snapshot.id in self._executions
                or request.snapshot.id in self._imported_shapes
            )
        if not known:
            return self._failed_operation(
                request.request_id,
                BackendOperation.INSPECT,
                BackendDiagnosticCode.INSPECTION_FAILED,
                f"unknown CadQuery state {request.snapshot.id!r}",
            )
        return BackendOperationResult(
            request_id=request.request_id,
            backend_id=self.descriptor.backend_id,
            backend_version=self.descriptor.backend_version,
            operation=BackendOperation.INSPECT,
            status=OperationStatus.SUCCEEDED,
            snapshot=request.snapshot,
        )

    def export_native(self, request: ExportRequest) -> BackendOperationResult:
        return unsupported_operation_result(
            self.descriptor,
            request.request_id,
            BackendOperation.EXPORT_NATIVE,
            "CadQuery has no editable native document artifact",
        )

    def _export(
        self,
        request: ExportRequest,
        operation: BackendOperation,
        kind: ArtifactKind,
        suffix: str,
        media_type: str,
    ) -> BackendOperationResult:
        if self.artifact_root is None:
            return self._failed_operation(
                request.request_id,
                operation,
                BackendDiagnosticCode.EXPORT_FAILED,
                "adapter has no configured artifact root",
            )
        with self._lock:
            execution = self._executions.get(request.snapshot.id)
        if execution is None:
            return self._failed_operation(
                request.request_id,
                operation,
                BackendDiagnosticCode.EXPORT_FAILED,
                f"unknown or non-exportable state {request.snapshot.id!r}",
            )
        try:
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            filename = f"{_safe_stem(request.request_id)}.{suffix}"
            path = self.artifact_root / filename
            (export_step if kind is ArtifactKind.NEUTRAL_MODEL else export_stl)(
                execution, path
            )
            artifact = ArtifactManifest(
                id=f"artifact:cadquery:{_safe_stem(request.request_id)}:{suffix}",
                kind=kind,
                filename=filename,
                media_type=media_type,
                content_sha256=_file_hash(path),
                byte_length=path.stat().st_size,
                backend_id=self.descriptor.backend_id,
                backend_version=self.descriptor.backend_version,
                source_feature_ir_sha256=request.snapshot.source_feature_ir_sha256,
            )
            with self._lock:
                self._artifact_paths[artifact.id] = path
            return BackendOperationResult(
                request_id=request.request_id,
                backend_id=self.descriptor.backend_id,
                backend_version=self.descriptor.backend_version,
                operation=operation,
                status=OperationStatus.SUCCEEDED,
                artifact=artifact,
            )
        except (OSError, ExecutionError, ValueError) as exc:
            return self._failed_operation(
                request.request_id,
                operation,
                BackendDiagnosticCode.EXPORT_FAILED,
                f"{type(exc).__name__}: {exc}",
            )

    def export_neutral(self, request: ExportRequest) -> BackendOperationResult:
        return self._export(
            request, BackendOperation.EXPORT_NEUTRAL,
            ArtifactKind.NEUTRAL_MODEL, "step", "model/step",
        )

    def export_preview(self, request: ExportRequest) -> BackendOperationResult:
        return self._export(
            request, BackendOperation.EXPORT_PREVIEW,
            ArtifactKind.PREVIEW_MODEL, "stl", "model/stl",
        )

    def verify_reimport(
        self, request: ReimportVerificationRequest
    ) -> BackendOperationResult:
        with self._lock:
            path = self._artifact_paths.get(request.artifact.id)
        if path is None:
            return self._failed_operation(
                request.request_id,
                BackendOperation.VERIFY_REIMPORT,
                BackendDiagnosticCode.REIMPORT_FAILED,
                f"artifact bytes are unavailable for {request.artifact.id!r}",
            )
        try:
            if _file_hash(path) != request.artifact.content_sha256:
                raise ValueError("artifact content hash changed before re-import")
            shape = import_step(path)
            if not shape.isValid() or len(shape.Solids()) != 1:
                raise ValueError("re-imported STEP is not one valid solid")
            snapshot = self._snapshot(
                request.request_id,
                request.expected_feature_ir_sha256,
                suffix=f"reimport:{request.artifact.content_sha256[:12]}",
            )
            with self._lock:
                self._imported_shapes[snapshot.id] = shape
            return BackendOperationResult(
                request_id=request.request_id,
                backend_id=self.descriptor.backend_id,
                backend_version=self.descriptor.backend_version,
                operation=BackendOperation.VERIFY_REIMPORT,
                status=OperationStatus.SUCCEEDED,
                snapshot=snapshot,
                reimport_verified=True,
            )
        except (OSError, ValueError) as exc:
            return self._failed_operation(
                request.request_id,
                BackendOperation.VERIFY_REIMPORT,
                BackendDiagnosticCode.REIMPORT_FAILED,
                f"{type(exc).__name__}: {exc}",
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
            backend_id=self.descriptor.backend_id,
            backend_version=self.descriptor.backend_version,
            operation=operation,
            status=OperationStatus.FAILED,
            diagnostics=(self._diagnostic(request_id, operation, code, message),),
        )

    def execution_for(self, snapshot: StateSnapshot) -> ExecutionResult:
        """Return the retained in-process result to legacy governed validators."""
        with self._lock:
            execution = self._executions.get(snapshot.id)
        if execution is None:
            raise ExecutionError(f"unknown CadQuery state {snapshot.id!r}")
        return execution

    def csg_for(self, snapshot: StateSnapshot) -> CADStateGraph:
        with self._lock:
            graph = self._csgs.get(snapshot.id)
        if graph is None:
            raise ExecutionError(f"unknown CadQuery CSG for state {snapshot.id!r}")
        return graph

    def execute_legacy(
        self, program: CADProgram, values: dict[str, float]
    ) -> ExecutionResult:
        """Transitional adapter path for pre-Feature-IR capability families."""
        return execute(program, values)

    def import_neutral_shape(self, path: Path):
        """Transitional adapter path used by the established STEP release check."""
        return import_step(path)
