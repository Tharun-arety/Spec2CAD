"""CAD State Graph is a closed immutable observation schema."""

import json

import pytest
from pydantic import ValidationError

from spec2cad.schemas.cad_state_graph import (
    ArtifactNode,
    BodyNode,
    CADStateGraph,
    ConstraintNode,
    ConstraintObservation,
    CSGRelationship,
    DatumKind,
    DatumReferenceNode,
    DiagnosticNode,
    DiagnosticSeverity,
    DocumentNode,
    GeometryKind,
    NativeFeatureNode,
    NativeConcept,
    ObservedQuantity,
    ParameterExpressionNode,
    QuantityUnit,
    RecomputeObservation,
    ReferenceNamespace,
    GraphReference,
    RelationshipKind,
    SemanticTopologyNode,
    SketchGeometryNode,
    SketchNode,
    TopologyKind,
    UnavailabilityKind,
    UnavailableConceptNode,
    validate_csg_provenance,
)
from pathlib import Path

from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.pipeline import run


HASH = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def observed_graph() -> CADStateGraph:
    parameter = ParameterExpressionNode(
        id="param.plate_width",
        label="Plate width",
        backend_native_id="Parameters.plate_width",
        parameter_name="plate_width",
        value=45.0,
        unit=QuantityUnit.MILLIMETRE,
        editable=True,
        native_expression="45 mm",
    )
    datum = DatumReferenceNode(
        id="datum.xy_plane",
        label="XY plane",
        datum_kind=DatumKind.PLANE,
        origin=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
    )
    line = SketchGeometryNode(
        id="geometry.base_line_bottom",
        label="Bottom line",
        backend_native_id="BaseSketch.Geometry.bottom",
        geometry_kind=GeometryKind.LINE,
        coordinates=(-22.5, -25.0, 22.5, -25.0),
    )
    constraint = ConstraintNode(
        id="constraint.base_width",
        label="Base width",
        backend_native_id="BaseSketch.Constraint.width",
        constraint_type="distance_x",
        geometry_ids=(line.id,),
        state=ConstraintObservation.SATISFIED,
        value=45.0,
        unit=QuantityUnit.MILLIMETRE,
        expression_id=parameter.id,
    )
    sketch = SketchNode(
        id="sketch.base",
        label="Base sketch",
        backend_native_id="BaseSketch",
        support_reference_id=datum.id,
        geometry_ids=(line.id,),
        constraint_ids=(constraint.id,),
        fully_constrained=True,
        degrees_of_freedom=0,
    )
    topology = SemanticTopologyNode(
        id="topology.base_top_surface",
        label="Base top surface",
        backend_native_id="semantic:base_top_surface",
        topology_kind=TopologyKind.FACE,
        semantic_role="base_top_surface",
        geometry_type="plane",
        signature_sha256="b" * 64,
        centroid_mm=(0.0, 0.0, 5.0),
        direction=(0.0, 0.0, 1.0),
        measurements=(ObservedQuantity(
            name="area", value=2000.0, unit=QuantityUnit.SQUARE_MILLIMETRE
        ),),
    )
    feature = NativeFeatureNode(
        id="feature.pad",
        label="Pad",
        backend_native_id="Pad",
        native_feature_type="PartDesign::Pad",
        portable_feature_type="pad",
        sequence_index=1,
        input_ids=(sketch.id, parameter.id),
        output_topology_ids=(topology.id,),
    )
    body = BodyNode(
        id="body.main",
        label="Main body",
        backend_native_id="Body",
        feature_ids=(sketch.id, feature.id),
        solid_count=1,
        measurements=(ObservedQuantity(
            name="volume", value=9000.0, unit=QuantityUnit.CUBIC_MILLIMETRE
        ),),
    )
    document = DocumentNode(
        id="document.motor_adapter",
        label="Motor adapter",
        backend_native_id="MotorAdapter",
        native_format="FCStd",
        editable=True,
        recompute=RecomputeObservation.SUCCEEDED,
        body_ids=(body.id,),
    )
    artifact = ArtifactNode(
        id="artifact.native",
        label="Native document",
        artifact_kind="native_model",
        filename="motor.FCStd",
        media_type="application/vnd.freecad",
        content_sha256="c" * 64,
        byte_length=100,
    )
    diagnostic = DiagnosticNode(
        id="diagnostic.recompute",
        label="Recompute status",
        severity=DiagnosticSeverity.INFO,
        code="recompute_ok",
        message="document recomputed",
        related_node_ids=(document.id,),
    )
    return CADStateGraph(
        id="csg.motor_adapter.r1",
        build_request_id="build:motor:r1",
        backend_id="freecad",
        backend_version="1.0",
        source_feature_ir_sha256=HASH,
        root_document_id=document.id,
        nodes=(
            document, body, datum, parameter, line, constraint, sketch,
            topology, feature, artifact, diagnostic,
        ),
    )


def test_all_r1_node_kinds_round_trip_as_closed_immutable_data():
    graph = observed_graph()
    kinds = {node.kind for node in graph.nodes}
    assert kinds == {
        "document", "body", "datum_reference", "parameter_expression",
        "sketch_geometry", "constraint", "sketch", "semantic_topology",
        "native_feature", "artifact", "diagnostic",
    }
    restored = CADStateGraph.model_validate_json(graph.model_dump_json())
    assert restored == graph
    assert json.loads(graph.model_dump_json())["schema_version"] == "1.0.0"


def test_global_ids_and_internal_references_are_validated():
    graph = observed_graph()
    with pytest.raises(ValidationError, match="globally unique"):
        CADStateGraph.model_validate({
            **graph.model_dump(), "nodes": (*graph.nodes, graph.nodes[-1])
        })
    broken = graph.nodes[1].model_copy(update={"feature_ids": ("feature.missing",)})
    with pytest.raises(ValidationError, match="invalid node"):
        CADStateGraph.model_validate({
            **graph.model_dump(), "nodes": (graph.nodes[0], broken, *graph.nodes[2:])
        })


def test_topology_identity_cannot_be_a_raw_backend_index():
    topology = next(
        node for node in observed_graph().nodes if node.kind == "semantic_topology"
    )
    with pytest.raises(ValidationError, match="raw index"):
        SemanticTopologyNode.model_validate({
            **topology.model_dump(), "backend_native_id": "Face1"
        })


def test_sketch_geometry_and_constraint_invariants_fail_closed():
    with pytest.raises(ValidationError, match="requires 4 coordinates"):
        SketchGeometryNode(
            id="geometry.bad",
            label="Bad line",
            geometry_kind="line",
            coordinates=(0.0, 1.0),
        )
    with pytest.raises(ValidationError, match="cannot have degrees"):
        SketchNode(
            id="sketch.bad",
            label="Bad sketch",
            fully_constrained=True,
            degrees_of_freedom=2,
        )


def test_unknown_node_kind_and_native_object_fields_are_rejected():
    graph = observed_graph().model_dump(mode="json")
    graph["nodes"][0]["native_shape"] = "arbitrary kernel object"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CADStateGraph.model_validate(graph)

    graph = observed_graph().model_dump(mode="json")
    graph["nodes"][0]["kind"] = "invented_native_object"
    with pytest.raises(ValidationError, match="does not match any"):
        CADStateGraph.model_validate(graph)


def _ref(namespace, record_id):
    return GraphReference(namespace=namespace, id=record_id)


def test_all_relationship_kinds_are_typed_and_provenance_resolves():
    run_result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    eig = run_result.latest.intent_graph
    feature_ir = compile_feature_ir(eig)
    pad = next(item for item in feature_ir.features if item.type == "pad")
    intent_id = pad.intent_links[0].eig_node_id
    interface_id = feature_ir.interfaces[0].id
    csg = ReferenceNamespace.CAD_STATE_GRAPH
    fir = ReferenceNamespace.FEATURE_IR
    eig_ns = ReferenceNamespace.ENGINEERING_INTENT_GRAPH
    relationships = (
        CSGRelationship(
            id="rel.feature_intent", kind=RelationshipKind.REALIZES_INTENT,
            source=_ref(csg, "feature.pad"), target=_ref(eig_ns, intent_id),
        ),
        CSGRelationship(
            id="rel.feature_ir", kind=RelationshipKind.REALIZES_FEATURE_IR,
            source=_ref(csg, "feature.pad"), target=_ref(fir, pad.id),
        ),
        CSGRelationship(
            id="rel.feature_dependency", kind=RelationshipKind.DEPENDS_ON,
            source=_ref(csg, "feature.pad"), target=_ref(csg, "sketch.base"),
        ),
        CSGRelationship(
            id="rel.constraint_reference", kind=RelationshipKind.REFERENCES,
            source=_ref(csg, "constraint.base_width"),
            target=_ref(csg, "param.plate_width"),
        ),
        CSGRelationship(
            id="rel.sketch_constraint", kind=RelationshipKind.CONSTRAINED_BY,
            source=_ref(csg, "sketch.base"),
            target=_ref(csg, "constraint.base_width"),
        ),
        CSGRelationship(
            id="rel.feature_profile", kind=RelationshipKind.CONSUMES_PROFILE,
            source=_ref(csg, "feature.pad"), target=_ref(csg, "sketch.base"),
        ),
        CSGRelationship(
            id="rel.feature_topology", kind=RelationshipKind.PRODUCES_TOPOLOGY,
            source=_ref(csg, "feature.pad"),
            target=_ref(csg, "topology.base_top_surface"),
        ),
        CSGRelationship(
            id="rel.topology_interface",
            kind=RelationshipKind.CORRESPONDS_TO_INTERFACE,
            source=_ref(csg, "topology.base_top_surface"),
            target=_ref(fir, interface_id),
        ),
    )
    graph = observed_graph().model_copy(update={"relationships": relationships})
    graph = CADStateGraph.model_validate(graph.model_dump())
    assert {item.kind for item in graph.relationships} == set(RelationshipKind)
    validate_csg_provenance(graph, intent_graph=eig, feature_ir=feature_ir)


def test_relationship_namespaces_structure_and_external_ids_fail_closed():
    csg = ReferenceNamespace.CAD_STATE_GRAPH
    eig_ns = ReferenceNamespace.ENGINEERING_INTENT_GRAPH
    with pytest.raises(ValidationError, match="target must use"):
        CSGRelationship(
            id="rel.bad_namespace",
            kind=RelationshipKind.REALIZES_FEATURE_IR,
            source=_ref(csg, "feature.pad"),
            target=_ref(eig_ns, "feature.pad"),
        )

    bad = CSGRelationship(
        id="rel.bad_constraint",
        kind=RelationshipKind.CONSTRAINED_BY,
        source=_ref(csg, "feature.pad"),
        target=_ref(csg, "constraint.base_width"),
    )
    with pytest.raises(ValidationError, match="sketch to constraint"):
        CADStateGraph.model_validate({
            **observed_graph().model_dump(), "relationships": (bad,)
        })

    external = CSGRelationship(
        id="rel.missing_intent",
        kind=RelationshipKind.REALIZES_INTENT,
        source=_ref(csg, "feature.pad"),
        target=_ref(eig_ns, "missing.intent"),
    )
    graph = CADStateGraph.model_validate({
        **observed_graph().model_dump(), "relationships": (external,)
    })
    run_result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    with pytest.raises(ValueError, match="missing EIG node"):
        validate_csg_provenance(graph, intent_graph=run_result.latest.intent_graph)


@pytest.mark.parametrize("status", list(UnavailabilityKind))
def test_absent_and_unsupported_native_concepts_are_explicit(status):
    node = UnavailableConceptNode(
        id=f"unavailable.native_document.{status.value}",
        label="Native editable document",
        concept=NativeConcept.EDITABLE_DOCUMENT,
        status=status,
        reason="backend does not have a native document object",
        requested_feature_ir_ids=("fir_motor_adapter_plate_r1",),
    )
    graph = CADStateGraph.model_validate({
        **observed_graph().model_dump(), "nodes": (*observed_graph().nodes, node)
    })
    assert graph.nodes[-1].status is status


def test_unavailable_concept_cannot_claim_observed_or_omit_reason():
    with pytest.raises(ValidationError):
        UnavailableConceptNode(
            id="unavailable.native_document",
            label="Native editable document",
            concept="editable_document",
            status="observed",
            reason="not a valid negative state",
        )
    with pytest.raises(ValidationError, match="at least 1 character"):
        UnavailableConceptNode(
            id="unavailable.native_document",
            label="Native editable document",
            concept="editable_document",
            status="absent",
            reason="",
        )
