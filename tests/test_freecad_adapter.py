"""The isolated FreeCAD worker conforms to the shared backend protocol."""

from pathlib import Path

import pytest

from spec2cad.backends import (
    ArtifactKind,
    BackendOperation,
    BuildRequest,
    BuildStatus,
    CADBackend,
    ExportRequest,
    InspectRequest,
    OperationStatus,
    ReimportVerificationRequest,
)
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import FreeCADWorkerUnavailable, discover_freecad_cmd
from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.schemas.cad_state_graph import validate_csg_provenance
from spec2cad.reconciliation import extract_motor_observations, reconcile_motor_geometry


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def test_real_freecad_adapter_build_inspect_and_exports(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    revision = repair(result, "widen_to_recommended", approved_by="adapter-test").latest
    document = compile_feature_ir(revision.intent_graph)
    adapter = FreeCADAdapter(tmp_path, executable=executable)
    assert isinstance(adapter, CADBackend)
    request = BuildRequest(
        request_id="build:freecad:adapter:r2",
        backend_id="freecad",
        feature_ir=document,
        feature_ir_manifest=feature_ir_manifest(document),
    )
    build = adapter.build(request)
    assert build.status is BuildStatus.SUCCEEDED
    assert build.snapshot.recompute_state.value == "succeeded"
    graph = adapter.csg_for(build.snapshot)
    validate_csg_provenance(
        graph, intent_graph=revision.intent_graph, feature_ir=document
    )
    assert build.snapshot.state_graph_sha256 == csg_manifest(graph).content_sha256
    assert adapter.inspect(InspectRequest(
        request_id="inspect:freecad:r2", snapshot=build.snapshot
    )).status is OperationStatus.SUCCEEDED

    operations = (
        (adapter.export_native, BackendOperation.EXPORT_NATIVE, ArtifactKind.NATIVE_MODEL),
        (adapter.export_neutral, BackendOperation.EXPORT_NEUTRAL, ArtifactKind.NEUTRAL_MODEL),
        (adapter.export_preview, BackendOperation.EXPORT_PREVIEW, ArtifactKind.PREVIEW_MODEL),
    )
    for method, operation, kind in operations:
        exported = method(ExportRequest(
            request_id=f"export:freecad:{kind.value}", snapshot=build.snapshot
        ))
        assert exported.operation is operation
        assert exported.status is OperationStatus.SUCCEEDED
        assert exported.artifact.kind is kind

    neutral = next(
        item for item in build.artifacts if item.kind is ArtifactKind.NEUTRAL_MODEL
    )
    verified = adapter.verify_reimport(ReimportVerificationRequest(
        request_id="verify:freecad:r2",
        artifact=neutral,
        expected_feature_ir_sha256=request.feature_ir_manifest.content_sha256,
    ))
    assert verified.status is OperationStatus.SUCCEEDED
    assert verified.reimport_verified is True


def test_feature_ir_identity_parameter_edit_recomputes_and_reconciles(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    v1 = result.latest
    v2 = repair(result, "widen_to_recommended", approved_by="native-edit-test").latest
    fir1, fir2 = compile_feature_ir(v1.intent_graph), compile_feature_ir(v2.intent_graph)
    adapter = FreeCADAdapter(tmp_path, executable=executable)
    initial = adapter.build(BuildRequest(
        request_id="build:freecad:native-edit:r1", backend_id="freecad",
        feature_ir=fir1, feature_ir_manifest=feature_ir_manifest(fir1),
    ))
    edited_request = BuildRequest(
        request_id="build:freecad:native-edit:r2", backend_id="freecad",
        feature_ir=fir2, feature_ir_manifest=feature_ir_manifest(fir2),
    )
    changed = next(
        after for before, after in zip(fir1.parameters, fir2.parameters)
        if before.value != after.value
    )
    edited = adapter.edit_parameter(
        initial.snapshot, edited_request,
        parameter_id=changed.id, parameter_value=changed.value,
    )
    assert edited.status is BuildStatus.SUCCEEDED
    graph = adapter.csg_for(edited.snapshot)
    width = next(
        node for node in graph.nodes
        if node.kind == "parameter_expression" and node.id.endswith(changed.id)
    )
    assert width.value == pytest.approx(changed.value)
    assert all(
        node.degrees_of_freedom == 0
        for node in graph.nodes if node.kind == "sketch"
    )
    cadquery = CadQueryAdapter()
    cq_build = cadquery.build(BuildRequest(
        request_id="build:cadquery:native-edit:r2", backend_id="cadquery",
        feature_ir=fir2, feature_ir_manifest=feature_ir_manifest(fir2),
    ))
    report = reconcile_motor_geometry(
        extract_motor_observations(
            v2.intent_graph, fir2, cadquery.csg_for(cq_build.snapshot)
        ),
        extract_motor_observations(v2.intent_graph, fir2, graph),
    )
    assert report.consistent
