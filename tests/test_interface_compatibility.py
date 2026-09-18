"""R3.1.3 validates intrinsic interface compatibility without an assembly."""

from pathlib import Path

import pytest

from spec2cad.interface_compatibility import (
    InterfaceCompatibilityStatus,
    assess_interface_compatibility,
    interface_compatibility_hash,
)
from spec2cad.pipeline import run
from spec2cad.schemas.intent_graph import (
    EngineeringIntentGraph,
    InterfaceCoordinateSystem,
    InterfaceGeometryBinding,
    InterfaceNode,
)


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
INTERFACE_ID = "iface_motor_mount"


@pytest.fixture(scope="module")
def compatible_pair():
    left_graph = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    ).latest.intent_graph
    left = left_graph.node(INTERFACE_ID)
    right_id = left.compatible_counterpart.id
    reciprocal = left.compatible_counterpart.model_copy(update={
        "id": left.id,
        "label": "Adapter plate counterpart",
    })
    right = left.model_copy(update={
        "id": right_id,
        "name": "motor_mount",
        "label": "Motor mounting interface",
        "compatible_counterpart": reciprocal,
    })
    nodes = tuple(
        right if item.id == left.id else item for item in left_graph.nodes
    )
    edges = tuple(
        edge.model_copy(update={
            "source": right_id if edge.source == left.id else edge.source,
            "target": right_id if edge.target == left.id else edge.target,
        })
        for edge in left_graph.edges
    )
    right_graph = EngineeringIntentGraph.model_validate({
        **left_graph.model_dump(),
        "nodes": nodes,
        "edges": edges,
    })
    return left_graph, left, right_graph, right


def replace_node(graph, replacement):
    return EngineeringIntentGraph.model_validate({
        **graph.model_dump(),
        "nodes": tuple(
            replacement if item.id == replacement.id else item
            for item in graph.nodes
        ),
    })


def replace_interface(graph, original_id, replacement):
    return EngineeringIntentGraph.model_validate({
        **graph.model_dump(),
        "nodes": tuple(
            replacement if item.id == original_id else item
            for item in graph.nodes
        ),
    })


def test_reciprocal_motor_interfaces_are_compatible_without_backend_or_assembly(
    compatible_pair,
):
    left_graph, left, right_graph, right = compatible_pair
    assessment = assess_interface_compatibility(
        left_graph, left.id, right_graph, right.id
    )
    assert assessment.status is InterfaceCompatibilityStatus.COMPATIBLE
    assert all(
        item.status is InterfaceCompatibilityStatus.COMPATIBLE
        for item in assessment.checks
    )
    assert assessment.dimension_tolerance_mm == pytest.approx(0.01)
    assert assessment.left_evidence_ids
    assert assessment.right_evidence_ids
    assert assessment.schema_version == "1.0.0"
    assert assessment.method_version == "1.0.0"


def test_dimension_tolerance_is_explicit_and_larger_drift_is_incompatible(
    compatible_pair,
):
    left_graph, left, right_graph, right = compatible_pair
    binding = next(
        item for item in right.governed_dimensions if item.role == "spacing_x"
    )
    dimension = right_graph.node(binding.dimension_id)
    within = dimension.model_copy(update={"value": float(dimension.value) + 0.005})
    within_graph = replace_node(right_graph, within)
    assert assess_interface_compatibility(
        left_graph, left.id, within_graph, right.id
    ).status is InterfaceCompatibilityStatus.COMPATIBLE

    outside = dimension.model_copy(update={"value": float(dimension.value) + 0.02})
    outside_graph = replace_node(right_graph, outside)
    assessment = assess_interface_compatibility(
        left_graph, left.id, outside_graph, right.id
    )
    assert assessment.status is InterfaceCompatibilityStatus.INCOMPATIBLE
    check = next(
        item for item in assessment.checks
        if item.id == "check.dimension.spacing_x"
    )
    assert check.status is InterfaceCompatibilityStatus.INCOMPATIBLE


def test_identity_coordinate_geometry_and_fit_mismatches_are_explicit(
    compatible_pair,
):
    left_graph, left, right_graph, right = compatible_pair
    wrong_counterpart = right.compatible_counterpart.model_copy(update={
        "id": "iface.unrelated"
    })
    wrong_identity = replace_interface(
        right_graph,
        right.id,
        right.model_copy(update={"compatible_counterpart": wrong_counterpart}),
    )
    identity = assess_interface_compatibility(
        left_graph, left.id, wrong_identity, right.id
    )
    assert next(
        item for item in identity.checks if item.id == "check.counterpart_identity"
    ).status is InterfaceCompatibilityStatus.INCOMPATIBLE

    rotated = InterfaceCoordinateSystem(
        id="coordinate.motor_mount.rotated",
        label="Rotated motor mount frame",
        origin_mm=(0.0, 0.0, 0.0),
        x_axis=(0.0, 1.0, 0.0),
        y_axis=(-1.0, 0.0, 0.0),
        z_axis=(0.0, 0.0, 1.0),
    )
    wrong_frame = replace_interface(
        right_graph,
        right.id,
        right.model_copy(update={"coordinate_system": rotated}),
    )
    frame = assess_interface_compatibility(
        left_graph, left.id, wrong_frame, right.id
    )
    assert next(
        item for item in frame.checks
        if item.id == "check.coordinate_convention"
    ).status is InterfaceCompatibilityStatus.INCOMPATIBLE

    geometry = right.governed_geometry[0]
    renamed = InterfaceGeometryBinding(
        role="different_pattern",
        node_id=geometry.node_id,
        geometry_kind=geometry.geometry_kind,
    )
    wrong_geometry = replace_interface(
        right_graph,
        right.id,
        right.model_copy(update={
            "governed_geometry": (renamed, *right.governed_geometry[1:])
        }),
    )
    geometry_result = assess_interface_compatibility(
        left_graph, left.id, wrong_geometry, right.id
    )
    assert next(
        item for item in geometry_result.checks
        if item.id == "check.geometry_roles"
    ).status is InterfaceCompatibilityStatus.INCOMPATIBLE

    wrong_fit = right.fit.model_copy(update={
        "tolerance_policy_version": "2.0.0"
    })
    fit_graph = replace_interface(
        right_graph, right.id, right.model_copy(update={"fit": wrong_fit})
    )
    fit_result = assess_interface_compatibility(
        left_graph, left.id, fit_graph, right.id
    )
    assert next(
        item for item in fit_result.checks if item.id == "check.fit_policy"
    ).status is InterfaceCompatibilityStatus.INCOMPATIBLE


def test_missing_or_legacy_interfaces_are_not_assessed():
    legacy = InterfaceNode(
        id="iface.legacy", label="Legacy interface", name="legacy"
    )
    graph = EngineeringIntentGraph(revision=1, nodes=[legacy])
    missing = assess_interface_compatibility(
        graph, "iface.missing", graph, legacy.id
    )
    assert missing.status is InterfaceCompatibilityStatus.NOT_ASSESSED
    incomplete = assess_interface_compatibility(
        graph, legacy.id, graph, legacy.id
    )
    assert incomplete.status is InterfaceCompatibilityStatus.NOT_ASSESSED


def test_unavailable_dimension_value_is_not_assessed(compatible_pair):
    left_graph, left, right_graph, right = compatible_pair
    binding = next(
        item for item in right.governed_dimensions if item.role == "spacing_y"
    )
    dimension = right_graph.node(binding.dimension_id)
    unavailable = dimension.model_copy(update={"value": None})
    unavailable_graph = replace_node(right_graph, unavailable)
    assessment = assess_interface_compatibility(
        left_graph, left.id, unavailable_graph, right.id
    )
    assert assessment.status is InterfaceCompatibilityStatus.NOT_ASSESSED
    check = next(
        item for item in assessment.checks
        if item.id == "check.dimension.spacing_y"
    )
    assert check.status is InterfaceCompatibilityStatus.NOT_ASSESSED


def test_assessment_serialization_and_hash_are_deterministic(compatible_pair):
    left_graph, left, right_graph, right = compatible_pair
    first = assess_interface_compatibility(
        left_graph, left.id, right_graph, right.id
    )
    second = assess_interface_compatibility(
        left_graph, left.id, right_graph, right.id
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert interface_compatibility_hash(first) == interface_compatibility_hash(second)
    assert len(interface_compatibility_hash(first)) == 64
