"""R3.1.1 first-class EIG interface intent is explicit and fail-closed."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.fusion.graph_builder import INTERFACE_NODE
from spec2cad.pipeline import run
from spec2cad.schemas.intent_graph import (
    EdgeKind,
    EngineeringIntentGraph,
    InterfaceCoordinateSystem,
    InterfaceDimensionBinding,
    InterfaceGeometryBinding,
    InterfaceNode,
    InterfaceType,
)


MOTOR = Path(__file__).resolve().parents[1] / "examples" / "motor_adapter"


def motor_graph():
    return run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    ).latest.intent_graph


def test_real_motor_interface_is_complete_without_copying_dimension_values():
    graph = motor_graph()
    interface = graph.node(INTERFACE_NODE)

    assert isinstance(interface, InterfaceNode)
    assert interface.contract_version == "1.0.0"
    assert interface.interface_type is InterfaceType.MOUNTING_PATTERN
    assert interface.coordinate_system.id == "coordinate.iface_motor_mount"
    assert interface.coordinate_system.origin_mm == (0.0, 0.0, 0.0)
    assert interface.coordinate_system.z_axis == (0.0, 0.0, 1.0)
    assert {
        (item.role, item.node_id) for item in interface.governed_geometry
    } == {
        ("mounting_pattern", "mounting_holes"),
        ("pilot_opening", "shaft_opening"),
    }
    dimensions = {item.role: item for item in interface.governed_dimensions}
    assert set(dimensions) == {
        "hole_count", "hole_diameter", "spacing_x", "spacing_y",
        "opening_diameter",
    }
    assert all(item.protected for item in dimensions.values())
    assert interface.protected_parameter_ids == tuple(sorted(
        item.dimension_id for item in dimensions.values()
    ))
    assert all(
        "value" not in type(item).model_fields for item in dimensions.values()
    )
    assert interface.fit.fit_kind.value == "clearance"
    assert interface.fit.tolerance_policy_id == "policy.interface.iso_273"
    assert interface.fit.tolerance_policy_version == "1.0.0"
    assert interface.compatible_counterpart.id == "counterpart.motor_mount"
    assert set(interface.compatible_counterpart.source_evidence_ids) == set(
        graph.supporting_evidence(interface.id)
    )


def test_coordinate_system_rejects_nonorthogonal_and_left_handed_axes():
    with pytest.raises(ValidationError, match="orthonormal"):
        InterfaceCoordinateSystem(
            id="coordinate.bad",
            label="Bad frame",
            origin_mm=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(1.0, 0.0, 0.0),
            z_axis=(0.0, 0.0, 1.0),
        )
    with pytest.raises(ValidationError, match="right-handed"):
        InterfaceCoordinateSystem(
            id="coordinate.left_handed",
            label="Left-handed frame",
            origin_mm=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
            z_axis=(0.0, 0.0, -1.0),
        )


def test_interface_contract_rejects_duplicate_roles_and_protection_drift():
    graph = motor_graph()
    interface = graph.node(INTERFACE_NODE)
    duplicate = interface.model_copy(update={
        "governed_geometry": (
            InterfaceGeometryBinding(
                role="mounting_pattern", node_id="mounting_holes"
            ),
            InterfaceGeometryBinding(
                role="mounting_pattern", node_id="shaft_opening"
            ),
        )
    })
    with pytest.raises(ValidationError, match="geometry roles must be unique"):
        InterfaceNode.model_validate(duplicate.model_dump())

    drifted = interface.model_copy(update={"protected_parameter_ids": ()})
    nodes = [
        drifted if item.id == interface.id else item for item in graph.nodes
    ]
    with pytest.raises(ValidationError, match="protected parameter ids"):
        EngineeringIntentGraph.model_validate(
            graph.model_copy(update={"nodes": nodes}).model_dump()
        )


def test_graph_requires_exact_dimension_geometry_and_provenance_links():
    graph = motor_graph()
    interface = graph.node(INTERFACE_NODE)
    edges = [
        edge for edge in graph.edges
        if not (
            edge.target == interface.id
            and edge.kind is EdgeKind.DEFINES
            and edge.role == "spacing_x"
        )
    ]
    with pytest.raises(ValidationError, match="dimension bindings must match"):
        EngineeringIntentGraph.model_validate(
            graph.model_copy(update={"edges": edges}).model_dump()
        )

    bad_geometry = interface.model_copy(update={
        "governed_geometry": (
            *interface.governed_geometry,
            InterfaceGeometryBinding(role="missing", node_id="feature.missing"),
        )
    })
    nodes = [
        bad_geometry if item.id == interface.id else item for item in graph.nodes
    ]
    with pytest.raises(ValidationError, match="missing geometry node"):
        EngineeringIntentGraph.model_validate(
            graph.model_copy(update={"nodes": nodes}).model_dump()
        )

    counterpart = interface.compatible_counterpart.model_copy(update={
        "source_evidence_ids": ("evidence.missing",)
    })
    uncited = interface.model_copy(update={"compatible_counterpart": counterpart})
    nodes = [
        uncited if item.id == interface.id else item for item in graph.nodes
    ]
    with pytest.raises(ValidationError, match="counterpart provenance"):
        EngineeringIntentGraph.model_validate(
            graph.model_copy(update={"nodes": nodes}).model_dump()
        )


def test_legacy_minimal_interface_payload_remains_readable():
    legacy = InterfaceNode(
        id="iface.legacy", label="Legacy interface", name="legacy"
    )
    assert legacy.coordinate_system is None
    assert legacy.governed_geometry == ()
    assert legacy.governed_dimensions == ()
    assert legacy.contract_complete is False
