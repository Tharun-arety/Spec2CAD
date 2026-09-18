"""R3.2.1 validates supplied two-component placement from semantic frames."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.assembly_placement import (
    PlacedInterface,
    PlacementStatus,
    RigidTransform,
    SemanticPlacementRequest,
    semantic_placement_hash,
    validate_semantic_placement,
)
from spec2cad.pipeline import run
from spec2cad.schemas.intent_graph import EngineeringIntentGraph, InterfaceNode


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


def request_for(graph, left=RigidTransform(), right=RigidTransform()):
    return SemanticPlacementRequest(
        id="placement.motor_adapter",
        components=(
            PlacedInterface(
                component_id="adapter",
                interface_id=INTERFACE_ID,
                design_revision=graph.revision,
                transform=left,
            ),
            PlacedInterface(
                component_id="motor",
                interface_id=INTERFACE_ID,
                design_revision=graph.revision,
                transform=right,
            ),
        ),
    )


def test_identity_placement_passes_semantic_axis_and_plane_checks(motor_graph):
    assessment = validate_semantic_placement(
        request_for(motor_graph),
        {"adapter": motor_graph, "motor": motor_graph},
    )
    assert assessment.status is PlacementStatus.PASS
    assert {item.id for item in assessment.checks} == {
        "check.semantic_axis_angle",
        "check.semantic_axis_radial_offset",
        "check.semantic_plane_separation",
    }
    assert all(item.actual == pytest.approx(0.0) for item in assessment.checks)


def test_common_rigid_transform_and_opposed_normal_remain_valid(motor_graph):
    common = RigidTransform(
        translation_mm=(12.0, -4.0, 7.0),
        rotation_axis=(0.0, 0.0, 1.0),
        rotation_degrees=90.0,
    )
    translated = validate_semantic_placement(
        request_for(motor_graph, common, common),
        {"adapter": motor_graph, "motor": motor_graph},
    )
    assert translated.status is PlacementStatus.PASS

    opposed = RigidTransform(
        rotation_axis=(1.0, 0.0, 0.0), rotation_degrees=180.0
    )
    flipped = validate_semantic_placement(
        request_for(motor_graph, RigidTransform(), opposed),
        {"adapter": motor_graph, "motor": motor_graph},
    )
    assert flipped.status is PlacementStatus.PASS


@pytest.mark.parametrize(
    ("transform", "failed_check"),
    (
        (
            RigidTransform(translation_mm=(0.02, 0.0, 0.0)),
            "check.semantic_axis_radial_offset",
        ),
        (
            RigidTransform(translation_mm=(0.0, 0.0, 0.02)),
            "check.semantic_plane_separation",
        ),
        (
            RigidTransform(
                rotation_axis=(1.0, 0.0, 0.0), rotation_degrees=1.0
            ),
            "check.semantic_axis_angle",
        ),
    ),
)
def test_radial_plane_and_angular_misplacement_fail_explicitly(
    motor_graph, transform, failed_check
):
    assessment = validate_semantic_placement(
        request_for(motor_graph, right=transform),
        {"adapter": motor_graph, "motor": motor_graph},
    )
    assert assessment.status is PlacementStatus.FAIL
    check = next(item for item in assessment.checks if item.id == failed_check)
    assert check.status is PlacementStatus.FAIL
    assert check.actual > check.limit


def test_missing_revision_or_legacy_semantic_frame_is_not_assessed(motor_graph):
    missing = validate_semantic_placement(
        request_for(motor_graph), {"adapter": motor_graph}
    )
    assert missing.status is PlacementStatus.NOT_ASSESSED

    wrong_revision = request_for(motor_graph).model_copy(update={
        "components": (
            request_for(motor_graph).components[0].model_copy(update={
                "design_revision": motor_graph.revision + 1
            }),
            request_for(motor_graph).components[1],
        )
    })
    mismatch = validate_semantic_placement(
        wrong_revision, {"adapter": motor_graph, "motor": motor_graph}
    )
    assert mismatch.status is PlacementStatus.NOT_ASSESSED

    legacy = InterfaceNode(
        id="iface.legacy", label="Legacy interface", name="legacy"
    )
    legacy_graph = EngineeringIntentGraph(revision=1, nodes=[legacy])
    legacy_request = SemanticPlacementRequest(
        id="placement.legacy",
        components=(
            PlacedInterface(
                component_id="a", interface_id=legacy.id, design_revision=1
            ),
            PlacedInterface(
                component_id="b", interface_id=legacy.id, design_revision=1
            ),
        ),
    )
    incomplete = validate_semantic_placement(
        legacy_request, {"a": legacy_graph, "b": legacy_graph}
    )
    assert incomplete.status is PlacementStatus.NOT_ASSESSED


def test_invalid_transforms_and_duplicate_components_are_rejected(motor_graph):
    with pytest.raises(ValidationError, match="finite"):
        RigidTransform(translation_mm=(float("nan"), 0.0, 0.0))
    with pytest.raises(ValidationError, match="non-zero"):
        RigidTransform(rotation_axis=(0.0, 0.0, 0.0))
    duplicate = request_for(motor_graph).model_dump()
    duplicate["components"][1]["component_id"] = "adapter"
    with pytest.raises(ValidationError, match="exactly two components"):
        SemanticPlacementRequest.model_validate(duplicate)


def test_placement_assessment_serialization_and_hash_are_deterministic(motor_graph):
    request = request_for(motor_graph)
    graphs = {"adapter": motor_graph, "motor": motor_graph}
    first = validate_semantic_placement(request, graphs)
    second = validate_semantic_placement(request, graphs)
    assert first.model_dump_json() == second.model_dump_json()
    assert semantic_placement_hash(first) == semantic_placement_hash(second)
    assert len(semantic_placement_hash(first)) == 64
