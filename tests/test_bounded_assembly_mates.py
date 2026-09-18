"""R3.2.2 solves only the declared translation-only semantic mate case."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.assembly_mates import (
    BoundedMateSolveRequest,
    CoincidentInterfacePlaneMate,
    ConcentricInterfaceMate,
    MateSolveStatus,
    OffsetInterfacePlaneMate,
    bounded_mate_result_hash,
    solve_bounded_interface_mates,
)
from spec2cad.assembly_placement import (
    PlacedInterface,
    PlacementStatus,
    RigidTransform,
    SemanticPlacementRequest,
)
from spec2cad.pipeline import run


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
INTERFACE_ID = "iface_motor_mount"


@pytest.fixture(scope="module")
def motor_graph():
    return run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    ).latest.intent_graph


def solve_request(graph, *, movable_transform=RigidTransform(), offset=None):
    placement = SemanticPlacementRequest(
        id="placement.to_solve",
        components=(
            PlacedInterface(
                component_id="adapter",
                interface_id=INTERFACE_ID,
                design_revision=graph.revision,
            ),
            PlacedInterface(
                component_id="motor",
                interface_id=INTERFACE_ID,
                design_revision=graph.revision,
                transform=movable_transform,
            ),
        ),
    )
    plane = (
        CoincidentInterfacePlaneMate(
            id="plane",
            component_a="adapter",
            component_b="motor",
        )
        if offset is None else
        OffsetInterfacePlaneMate(
            id="plane",
            component_a="adapter",
            component_b="motor",
            distance_mm=offset,
        )
    )
    return BoundedMateSolveRequest(
        id="solve.motor_mount",
        placement=placement,
        fixed_component_id="adapter",
        movable_component_id="motor",
        mates=(
            ConcentricInterfaceMate(
                id="axis",
                component_a="adapter",
                component_b="motor",
            ),
            plane,
        ),
    )


def test_concentric_and_coincident_mates_solve_one_translation(motor_graph):
    request = solve_request(
        motor_graph,
        movable_transform=RigidTransform(translation_mm=(5.0, -3.0, 2.0)),
    )
    result = solve_bounded_interface_mates(
        request, {"adapter": motor_graph, "motor": motor_graph}
    )
    assert result.status is MateSolveStatus.SOLVED
    assert result.validation.status is PlacementStatus.PASS
    components = {
        item.component_id: item for item in result.solved_placement.components
    }
    assert components["adapter"] == request.placement.components[0]
    assert components["motor"].transform.translation_mm == pytest.approx(
        (0.0, 0.0, 0.0)
    )
    assert components["motor"].transform.rotation_degrees == 0.0


@pytest.mark.parametrize("offset", (4.0, -2.5))
def test_signed_plane_offset_is_solved_and_revalidated(motor_graph, offset):
    request = solve_request(
        motor_graph,
        movable_transform=RigidTransform(translation_mm=(1.0, 2.0, 8.0)),
        offset=offset,
    )
    result = solve_bounded_interface_mates(
        request, {"adapter": motor_graph, "motor": motor_graph}
    )
    assert result.status is MateSolveStatus.SOLVED
    movable = next(
        item for item in result.solved_placement.components
        if item.component_id == "motor"
    )
    assert movable.transform.translation_mm == pytest.approx((0.0, 0.0, offset))
    assert result.solved_placement.plane_offset_mm == pytest.approx(offset)
    assert result.validation.status is PlacementStatus.PASS


def test_rotation_search_is_explicitly_unsupported(motor_graph):
    request = solve_request(
        motor_graph,
        movable_transform=RigidTransform(
            rotation_axis=(1.0, 0.0, 0.0),
            rotation_degrees=1.0,
        ),
    )
    result = solve_bounded_interface_mates(
        request, {"adapter": motor_graph, "motor": motor_graph}
    )
    assert result.status is MateSolveStatus.UNSUPPORTED
    assert result.solved_placement is None
    assert "does not search rotations" in result.message


def test_missing_authoritative_graph_fails_without_guessing(motor_graph):
    result = solve_bounded_interface_mates(
        solve_request(motor_graph), {"adapter": motor_graph}
    )
    assert result.status is MateSolveStatus.FAILED
    assert result.solved_placement is None


def test_overconstrained_or_badly_referenced_requests_are_rejected(motor_graph):
    request = solve_request(motor_graph)
    duplicate_axis = request.mates[0].model_copy(update={"id": "axis_two"})
    with pytest.raises(ValidationError, match="one concentric and one plane"):
        BoundedMateSolveRequest.model_validate({
            **request.model_dump(),
            "mates": (request.mates[0], duplicate_axis),
        })
    wrong_components = request.mates[0].model_copy(update={
        "component_b": "unrelated"
    })
    with pytest.raises(ValidationError, match="reference both components"):
        BoundedMateSolveRequest.model_validate({
            **request.model_dump(),
            "mates": (wrong_components, request.mates[1]),
        })


def test_bounded_solution_and_hash_are_deterministic(motor_graph):
    request = solve_request(
        motor_graph,
        movable_transform=RigidTransform(translation_mm=(3.0, 7.0, -9.0)),
        offset=1.25,
    )
    graphs = {"adapter": motor_graph, "motor": motor_graph}
    first = solve_bounded_interface_mates(request, graphs)
    second = solve_bounded_interface_mates(request, graphs)
    assert first.model_dump_json() == second.model_dump_json()
    assert bounded_mate_result_hash(first) == bounded_mate_result_hash(second)
    assert len(bounded_mate_result_hash(first)) == 64
