"""R3.1.2 interface geometry correspondence stays exact across all graphs."""

from pathlib import Path

import pytest

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import run
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    ReferenceNamespace,
    RelationshipKind,
    validate_csg_provenance,
)
from spec2cad.schemas.feature_ir import (
    FeatureIRProvenanceError,
    SurfaceSelector,
    validate_eig_provenance,
)


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


@pytest.fixture(scope="module")
def motor_correspondence():
    revision = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    ).latest
    document = compile_feature_ir(revision.intent_graph)
    adapter = CadQueryAdapter()
    build = adapter.build(BuildRequest(
        request_id="build:r3.1.2:motor",
        backend_id="cadquery",
        feature_ir=document,
        feature_ir_manifest=feature_ir_manifest(document),
    ))
    assert build.status is BuildStatus.SUCCEEDED
    return revision.intent_graph, document, adapter.csg_for(build.snapshot)


def test_complete_eig_geometry_compiles_to_exact_feature_ir_bindings(
    motor_correspondence,
):
    eig, document, _ = motor_correspondence
    interface = document.interfaces[0]
    assert interface.correspondence_version == "1.0.0"
    bindings = {item.role: item for item in interface.geometry_bindings}
    assert set(bindings) == {"mounting_pattern", "pilot_opening"}
    assert bindings["mounting_pattern"].eig_geometry_node_id == "mounting_holes"
    assert bindings["mounting_pattern"].feature_ids == (
        "fir_mounting_holes_seed_sketch",
        "fir_mounting_holes_seed_pocket",
        "fir_mounting_holes_pattern",
    )
    assert set(bindings["mounting_pattern"].parameter_ids) == {
        "dim_hole_spacing_x",
        "dim_hole_spacing_y",
        "dim_mounting_hole_count",
        "dim_mounting_hole_diameter",
    }
    assert bindings["pilot_opening"].feature_ids == (
        "fir_shaft_opening_sketch",
        "fir_shaft_opening_pocket",
    )
    assert bindings["pilot_opening"].parameter_ids == (
        "dim_shaft_opening_diameter",
    )
    assert all(
        item.reference.selector is SurfaceSelector.INNER_CYLINDER
        for item in bindings.values()
    )
    validate_eig_provenance(document, eig)


def test_feature_ir_correspondence_refuses_eig_geometry_drift(
    motor_correspondence,
):
    eig, document, _ = motor_correspondence
    interface = document.interfaces[0]
    binding = interface.geometry_bindings[0].model_copy(update={
        "eig_geometry_node_id": "external_chamfers"
    })
    drifted = interface.model_copy(update={
        "geometry_bindings": (binding, *interface.geometry_bindings[1:])
    })
    invalid = document.model_copy(update={"interfaces": (drifted,)})
    with pytest.raises(
        FeatureIRProvenanceError, match="do not exactly match"
    ):
        validate_eig_provenance(invalid, eig)


def test_cadquery_topology_has_paired_role_preserving_correspondence(
    motor_correspondence,
):
    eig, document, graph = motor_correspondence
    assert graph.interface_correspondence_version == "1.0.0"
    validate_csg_provenance(graph, intent_graph=eig, feature_ir=document)
    links = [
        item for item in graph.relationships
        if item.kind is RelationshipKind.CORRESPONDS_TO_INTERFACE
    ]
    assert {item.role for item in links} == {
        "mounting_pattern", "pilot_opening"
    }
    grouped = {}
    for item in links:
        grouped.setdefault((item.source.id, item.role), set()).add(
            item.target.namespace
        )
    assert grouped
    assert all(namespaces == {
        ReferenceNamespace.FEATURE_IR,
        ReferenceNamespace.ENGINEERING_INTENT_GRAPH,
    } for namespaces in grouped.values())
    assert sum(role == "mounting_pattern" for _, role in grouped) == 4
    assert sum(role == "pilot_opening" for _, role in grouped) == 1


def test_cad_state_correspondence_fails_closed_when_pair_is_missing(
    motor_correspondence,
):
    eig, document, graph = motor_correspondence
    removed = next(
        item for item in graph.relationships
        if item.kind is RelationshipKind.CORRESPONDS_TO_INTERFACE
        and item.target.namespace is ReferenceNamespace.ENGINEERING_INTENT_GRAPH
    )
    relationships = tuple(
        item for item in graph.relationships if item.id != removed.id
    )
    incomplete = CADStateGraph.model_validate({
        **graph.model_dump(), "relationships": relationships
    })
    with pytest.raises(ValueError, match="must pair Feature IR and EIG"):
        validate_csg_provenance(
            incomplete, intent_graph=eig, feature_ir=document
        )


def test_cad_state_interface_link_cannot_target_an_arbitrary_feature(
    motor_correspondence,
):
    eig, document, graph = motor_correspondence
    original = next(
        item for item in graph.relationships
        if item.kind is RelationshipKind.CORRESPONDS_TO_INTERFACE
        and item.target.namespace is ReferenceNamespace.FEATURE_IR
    )
    wrong = original.model_copy(update={
        "target": original.target.model_copy(
            update={"id": document.features[0].id}
        )
    })
    relationships = tuple(
        wrong if item.id == original.id else item for item in graph.relationships
    )
    invalid = CADStateGraph.model_validate({
        **graph.model_dump(), "relationships": relationships
    })
    with pytest.raises(ValueError, match="must target an interface record"):
        validate_csg_provenance(invalid, intent_graph=eig, feature_ir=document)
