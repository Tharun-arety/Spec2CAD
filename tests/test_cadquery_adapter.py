"""CadQuery realizes the governed motor slice through the backend protocol."""

from pathlib import Path

from spec2cad.backends import (
    ArtifactKind,
    BackendDiagnosticCode,
    BuildRequest,
    BuildResult,
    BuildStatus,
    ExportRequest,
    InspectRequest,
    OperationStatus,
    ReimportVerificationRequest,
)
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.cad.compiler import compile_design
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.pipeline import repair, run
from spec2cad.schemas.cad_state_graph import validate_csg_provenance
from spec2cad.schemas.feature_ir import FilletFeature


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def motor_revision(repaired=False):
    result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    return (
        repair(result, "widen_to_recommended", approved_by="adapter-test").latest
        if repaired else result.latest
    )


def request_for(revision, **changes):
    document = compile_feature_ir(revision.intent_graph)
    values = {
        "request_id": f"build:motor:r{revision.revision}",
        "backend_id": "cadquery",
        "feature_ir": document,
        "feature_ir_manifest": feature_ir_manifest(document),
    }
    values.update(changes)
    return BuildRequest(**values)


def test_pipeline_motor_revision_records_successful_protocol_build():
    revision = motor_revision()
    assert revision.feature_ir is not None
    assert revision.backend_result is not None
    assert revision.backend_result.status is BuildStatus.SUCCEEDED
    assert revision.backend_result.snapshot.source_feature_ir_sha256 == (
        feature_ir_manifest(revision.feature_ir).content_sha256
    )
    assert revision.program == compile_design(revision.intent_graph)


def test_adapter_build_and_inspect_both_motor_revisions():
    graph_hashes = []
    for repaired in (False, True):
        revision = motor_revision(repaired)
        adapter = CadQueryAdapter()
        result = adapter.build(request_for(revision))
        assert result.status is BuildStatus.SUCCEEDED
        assert adapter.execution_for(result.snapshot).shape.isValid()
        inspection = adapter.inspect(InspectRequest(
            request_id=f"inspect:r{revision.revision}", snapshot=result.snapshot
        ))
        assert inspection.status is OperationStatus.SUCCEEDED
        assert inspection.snapshot == result.snapshot
        graph = adapter.csg_for(result.snapshot)
        validate_csg_provenance(
            graph,
            intent_graph=revision.intent_graph,
            feature_ir=compile_feature_ir(revision.intent_graph),
        )
        manifest = csg_manifest(graph)
        assert result.snapshot.state_graph_id == graph.id
        assert result.snapshot.state_graph_sha256 == manifest.content_sha256
        assert not any(node.kind in {
            "sketch", "constraint", "parameter_expression", "native_feature"
        } for node in graph.nodes)
        unavailable = {
            node.concept.value for node in graph.nodes
            if node.kind == "unavailable_concept"
        }
        assert unavailable >= {
            "editable_document", "parametric_sketch", "sketch_constraint",
            "parameter_expression", "native_feature", "native_export",
        }
        assert len([
            node for node in graph.nodes if node.kind == "semantic_topology"
        ]) >= 6
        graph_hashes.append(manifest.content_sha256)
    assert graph_hashes[0] != graph_hashes[1]


def test_neutral_preview_exports_and_reimport_have_typed_manifests(tmp_path):
    revision = motor_revision(repaired=True)
    adapter = CadQueryAdapter(tmp_path)
    result = adapter.build(request_for(revision))
    snapshot = result.snapshot

    neutral = adapter.export_neutral(ExportRequest(
        request_id="export:motor:step", snapshot=snapshot
    ))
    preview = adapter.export_preview(ExportRequest(
        request_id="export:motor:preview", snapshot=snapshot
    ))
    assert neutral.status is preview.status is OperationStatus.SUCCEEDED
    assert neutral.artifact.kind is ArtifactKind.NEUTRAL_MODEL
    assert preview.artifact.kind is ArtifactKind.PREVIEW_MODEL
    assert (tmp_path / neutral.artifact.filename).stat().st_size == neutral.artifact.byte_length
    assert (tmp_path / preview.artifact.filename).stat().st_size == preview.artifact.byte_length

    verified = adapter.verify_reimport(ReimportVerificationRequest(
        request_id="verify:motor:step",
        artifact=neutral.artifact,
        expected_feature_ir_sha256=snapshot.source_feature_ir_sha256,
    ))
    assert verified.status is OperationStatus.SUCCEEDED
    assert verified.reimport_verified is True


def test_cadquery_explicitly_refuses_native_export(tmp_path):
    revision = motor_revision()
    adapter = CadQueryAdapter(tmp_path)
    result = adapter.build(request_for(
        revision, requested_artifacts=(ArtifactKind.NATIVE_MODEL,)
    ))
    assert result.status is BuildStatus.UNSUPPORTED
    assert result.snapshot is not None
    assert result.diagnostics[0].code is BackendDiagnosticCode.UNSUPPORTED_CAPABILITY


def test_fillet_is_supported_through_shared_feature_ir():
    revision = motor_revision()
    request = request_for(revision)
    document = request.feature_ir
    chamfer = document.features[-1]
    fillet = FilletFeature(
        id=chamfer.id,
        label=chamfer.label,
        intent_links=chamfer.intent_links,
        edges=chamfer.edges,
        radius=chamfer.distance,
    )
    filleted_document = document.model_copy(update={
        "features": (*document.features[:-1], fillet),
    })
    result = CadQueryAdapter().build(BuildRequest(
        request_id="build:motor:fillet",
        backend_id="cadquery",
        feature_ir=filleted_document,
        feature_ir_manifest=feature_ir_manifest(filleted_document),
    ))
    assert result.status is BuildStatus.SUCCEEDED
    assert result.diagnostics == ()
    assert BuildResult.model_validate_json(result.model_dump_json()) == result
