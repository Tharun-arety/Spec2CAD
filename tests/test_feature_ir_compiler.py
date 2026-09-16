"""EIG → Feature IR compilation for the motor-adapter slice."""

from pathlib import Path

import pytest

from spec2cad.feature_compiler import (
    FeatureIRCompilationError,
    compile_feature_ir,
)
from spec2cad.pipeline import repair, run
from spec2cad.schemas.feature_ir import (
    ChamferFeature,
    PadFeature,
    PocketFeature,
    RectangularPatternFeature,
    SketchFeature,
    validate_eig_provenance,
)


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
BRACKET = ROOT / "examples" / "mounting_bracket"


@pytest.fixture
def motor_v1():
    return run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )


def test_real_motor_eig_compiles_to_complete_backend_neutral_sequence(motor_v1):
    document = compile_feature_ir(motor_v1.latest.intent_graph)
    assert [type(item) for item in document.features] == [
        SketchFeature, PadFeature,
        SketchFeature, PocketFeature,
        SketchFeature, PocketFeature, RectangularPatternFeature,
        ChamferFeature,
    ]
    assert document.bodies[0].feature_ids == tuple(
        item.id for item in document.features
    )
    assert document.part.interface_ids == ("fir_iface_motor_mount",)
    assert document.interfaces[0].feature_ids == ("fir_mounting_holes_pattern",)
    validate_eig_provenance(document, motor_v1.latest.intent_graph)


def test_parameters_keep_names_values_and_interface_protection(motor_v1):
    document = compile_feature_ir(motor_v1.latest.intent_graph)
    parameters = {item.name: item for item in document.parameters}
    assert parameters["plate_width"].value == pytest.approx(40)
    assert parameters["mounting_hole_diameter"].value == pytest.approx(3.4)
    assert parameters["mounting_hole_count"].value == pytest.approx(4)
    assert parameters["mounting_hole_diameter"].protected is True
    assert parameters["hole_spacing_x"].protected is True
    assert parameters["plate_width"].protected is False


def test_v2_changes_revision_and_width_without_changing_feature_composition(motor_v1):
    repaired = repair(
        motor_v1, "widen_to_recommended", approved_by="feature-ir-test"
    )
    before = compile_feature_ir(motor_v1.latest.intent_graph)
    after = compile_feature_ir(repaired.latest.intent_graph)
    assert before.design_revision == 1 and after.design_revision == 2
    assert [type(item) for item in before.features] == [
        type(item) for item in after.features
    ]
    widths = [
        next(item.value for item in document.parameters if item.name == "plate_width")
        for document in (before, after)
    ]
    assert widths == pytest.approx([40, 45])


def test_compilation_is_byte_deterministic(motor_v1):
    first = compile_feature_ir(motor_v1.latest.intent_graph).model_dump_json()
    second = compile_feature_ir(motor_v1.latest.intent_graph).model_dump_json()
    assert first == second


def test_compiled_payload_contains_no_backend_or_native_selector_tokens(motor_v1):
    payload = compile_feature_ir(motor_v1.latest.intent_graph).model_dump_json()
    for forbidden in ("cadquery", "freecad", "Face1", ">Z"):
        assert forbidden not in payload


def test_slotted_filleted_bracket_compiles_to_bounded_feature_ir():
    bracket = run(requirement=BRACKET / "requirement.txt")
    document = compile_feature_ir(bracket.latest.intent_graph)
    assert [item.type for item in document.features] == [
        "sketch", "pad", "sketch", "pocket", "rectangular_pattern",
        "linear_slot_pattern", "fillet",
    ]
