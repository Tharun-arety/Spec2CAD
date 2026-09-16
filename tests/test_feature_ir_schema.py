"""Backend-neutral Feature IR schema contracts."""

import json

import pytest
from pydantic import ValidationError

from spec2cad.schemas.feature_ir import (
    BinaryExpression,
    BinaryOperator,
    ChamferFeature,
    CoincidentConstraint,
    DatumPlane,
    DatumPlaneReference,
    DiameterConstraint,
    EdgeSetSelector,
    FeatureEdgeSetReference,
    FeatureIR,
    FeatureIRBody,
    FeatureIRInterface,
    FeatureIRParameter,
    FeatureIRPart,
    FeatureSurfaceReference,
    FixedConstraint,
    GeometryPoint,
    GeometryPointReference,
    IntentLink,
    IntentRelation,
    PadFeature,
    ParameterKind,
    Point2D,
    PocketFeature,
    RectangularPatternFeature,
    SketchCircle,
    SketchDefinition,
    SketchFeature,
    SketchLine,
    SketchProfile,
    SurfaceSelector,
    literal,
    parameter,
    validate_eig_provenance,
    FeatureIRProvenanceError,
)


def point(x, y):
    return Point2D(x=literal(x), y=literal(y))


def links(node_id: str, relation: IntentRelation):
    return (IntentLink(eig_node_id=node_id, relation=relation),)


def motor_shaped_feature_ir() -> FeatureIR:
    parameters = (
        FeatureIRParameter(id="plate_width", name="plate_width", label="Plate width", intent_links=links("dim_plate_width", IntentRelation.PARAMETERIZES), kind=ParameterKind.LENGTH, value=45, unit="mm"),
        FeatureIRParameter(id="plate_height", name="plate_height", label="Plate height", intent_links=links("dim_plate_height", IntentRelation.PARAMETERIZES), kind=ParameterKind.LENGTH, value=50, unit="mm"),
        FeatureIRParameter(id="plate_thickness", name="plate_thickness", label="Plate thickness", intent_links=links("dim_plate_thickness", IntentRelation.PARAMETERIZES), kind=ParameterKind.LENGTH, value=5, unit="mm"),
        FeatureIRParameter(id="opening_diameter", name="opening_diameter", label="Opening diameter", intent_links=links("dim_shaft_opening_diameter", IntentRelation.PARAMETERIZES), kind=ParameterKind.LENGTH, value=22.5, unit="mm"),
        FeatureIRParameter(id="pattern_count", name="pattern_count", label="Pattern count", intent_links=links("dim_mounting_hole_count", IntentRelation.PARAMETERIZES), kind=ParameterKind.COUNT, value=2, unit="none"),
    )
    base_sketch = SketchFeature(
        id="base_sketch", label="Base sketch",
        intent_links=links("base_plate", IntentRelation.REALIZES),
        sketch=SketchDefinition(
            support=DatumPlaneReference(plane=DatumPlane.XY),
            geometry=(
                SketchLine(id="bottom", start=point(-22.5, -25), end=point(22.5, -25)),
                SketchLine(id="right", start=point(22.5, -25), end=point(22.5, 25)),
                SketchLine(id="top", start=point(22.5, 25), end=point(-22.5, 25)),
                SketchLine(id="left", start=point(-22.5, 25), end=point(-22.5, -25)),
            ),
            profiles=(SketchProfile(id="base_profile", label="Plate outline", geometry_ids=("bottom", "right", "top", "left")),),
            constraints=(FixedConstraint(id="base_fixed", geometry_ids=("bottom", "right", "top", "left")),),
        ),
    )
    pad = PadFeature(
        id="base_pad", label="Base pad", sketch_id="base_sketch",
        intent_links=links("base_plate", IntentRelation.REALIZES),
        profile_id="base_profile", length=parameter("plate_thickness"),
    )
    opening_sketch = SketchFeature(
        id="opening_sketch", label="Opening sketch",
        intent_links=links("shaft_opening", IntentRelation.REALIZES),
        sketch=SketchDefinition(
            support=FeatureSurfaceReference(
                feature_id="base_pad", selector=SurfaceSelector.POSITIVE_NORMAL,
            ),
            geometry=(SketchCircle(id="opening_circle", center=point(0, 0), diameter=parameter("opening_diameter")),),
            profiles=(SketchProfile(id="opening_profile", label="Opening", geometry_ids=("opening_circle",)),),
            constraints=(DiameterConstraint(id="opening_diameter_c", geometry_id="opening_circle", value=parameter("opening_diameter")),),
        ),
    )
    opening = PocketFeature(
        id="opening_pocket", label="Central pocket", sketch_id="opening_sketch",
        intent_links=links("shaft_opening", IntentRelation.REALIZES),
        profile_id="opening_profile",
    )
    pattern = RectangularPatternFeature(
        id="mounting_pattern", label="Mounting pattern",
        intent_links=links("mounting_holes", IntentRelation.REALIZES),
        source_feature_id="opening_pocket", count_x=parameter("pattern_count"),
        count_y=parameter("pattern_count"), spacing_x=literal(31), spacing_y=literal(31),
    )
    chamfer = ChamferFeature(
        id="edge_chamfer", label="External chamfer",
        intent_links=links("external_chamfers", IntentRelation.REALIZES),
        edges=FeatureEdgeSetReference(
            feature_id="base_pad", selector=EdgeSetSelector.EXTERNAL_PERIMETER,
        ),
        distance=literal(1),
    )
    features = (base_sketch, pad, opening_sketch, opening, pattern, chamfer)
    return FeatureIR(
        id="motor_adapter_r1", label="Motor adapter", design_revision=1,
        part=FeatureIRPart(
            id="motor_adapter", label="Motor adapter",
            name="motor_adapter",
            intent_links=links("part", IntentRelation.REALIZES),
            body_ids=("main_body",), interface_ids=("motor_mount",),
        ),
        bodies=(FeatureIRBody(id="main_body", label="Main body", intent_links=links("part", IntentRelation.GROUPS), feature_ids=tuple(item.id for item in features)),),
        parameters=parameters,
        features=features,
        interfaces=(FeatureIRInterface(
            id="motor_mount", label="Motor mount",
            intent_links=links("iface_motor_mount", IntentRelation.CORRESPONDS_TO),
            reference=FeatureSurfaceReference(feature_id="base_pad", selector=SurfaceSelector.POSITIVE_NORMAL),
            feature_ids=("mounting_pattern",),
            parameter_ids=("opening_diameter",),
        ),),
    )


def test_motor_shaped_document_round_trips_deterministically():
    document = motor_shaped_feature_ir()
    payload = json.loads(document.model_dump_json())
    assert payload["schema_version"] == "1.0.0"
    assert FeatureIR.model_validate(payload) == document
    assert document.features[1].length.parameter_id == "plate_thickness"


def test_expression_is_a_closed_recursive_ast():
    expression = BinaryExpression(
        operator=BinaryOperator.DIVIDE,
        left=parameter("plate_width"), right=literal(2),
    )
    assert expression.left.parameter_id == "plate_width"
    with pytest.raises(ValidationError):
        PadFeature(
            id="bad", label="bad", sketch_id="s", profile_id="p",
            intent_links=links("base_plate", IntentRelation.REALIZES),
            length="plate_width / 2",
        )


@pytest.mark.parametrize("selector", ["Face1", ">Z", "0"])
def test_raw_topology_indices_and_backend_selectors_are_rejected(selector):
    with pytest.raises(ValidationError):
        FeatureSurfaceReference(feature_id="base", selector=selector)


def test_unknown_backend_fields_and_feature_types_are_rejected():
    with pytest.raises(ValidationError):
        FeatureSurfaceReference(
            feature_id="base", selector="positive_normal", cadquery_selector=">Z"
        )
    payload = motor_shaped_feature_ir().model_dump(mode="json")
    payload["features"][0]["type"] = "freecad_pad"
    with pytest.raises(ValidationError):
        FeatureIR.model_validate(payload)


def test_parameters_enforce_units_counts_and_finite_values():
    with pytest.raises(ValidationError, match="length parameter requires unit mm"):
        FeatureIRParameter(id="x", name="x", label="x", intent_links=links("dim_plate_width", IntentRelation.PARAMETERIZES), kind="length", value=1, unit="none")
    with pytest.raises(ValidationError, match="positive integer"):
        FeatureIRParameter(id="n", name="n", label="n", intent_links=links("dim_mounting_hole_count", IntentRelation.PARAMETERIZES), kind="count", value=2.5, unit="none")
    with pytest.raises(ValidationError):
        FeatureIRParameter(id="x", name="x", label="x", intent_links=links("dim_plate_width", IntentRelation.PARAMETERIZES), kind="length", value=float("nan"), unit="mm")


def test_pocket_termination_contract_is_unambiguous():
    with pytest.raises(ValidationError, match="blind pocket requires depth"):
        PocketFeature(
            id="p", label="p", sketch_id="s", profile_id="profile",
            intent_links=links("shaft_opening", IntentRelation.REALIZES),
            termination="blind",
        )
    with pytest.raises(ValidationError, match="through_all forbids"):
        PocketFeature(
            id="p", label="p", sketch_id="s", profile_id="profile",
            intent_links=links("shaft_opening", IntentRelation.REALIZES),
            termination="through_all", depth=literal(5),
        )


def test_models_are_frozen_and_forbid_unknown_fields():
    document = motor_shaped_feature_ir()
    with pytest.raises(ValidationError):
        document.model_copy(update={"backend": "cadquery"}).model_validate(
            {**document.model_dump(mode="json"), "backend": "cadquery"}
        )
    with pytest.raises(Exception):
        document.design_revision = 3


@pytest.mark.parametrize("bad_id", ["", "has space", "Face1", ">Z", " leading"])
def test_stable_ids_use_a_portable_backend_neutral_grammar(bad_id):
    with pytest.raises(ValidationError):
        FeatureIRParameter(
            id=bad_id, name="bad", label="bad", kind="length", value=1, unit="mm",
            intent_links=links("dim_plate_width", IntentRelation.PARAMETERIZES),
        )


def test_duplicate_ids_are_rejected_across_nested_records():
    payload = motor_shaped_feature_ir().model_dump(mode="json")
    payload["features"][1]["id"] = "base_sketch"
    with pytest.raises(ValidationError, match="globally unique"):
        FeatureIR.model_validate(payload)


def test_provenance_traverses_an_actual_motor_adapter_eig():
    from pathlib import Path

    from spec2cad.pipeline import run

    example = Path(__file__).resolve().parents[1] / "examples" / "motor_adapter"
    result = run(
        example / "sketch.png", example / "motor_datasheet.pdf",
        example / "requirement.txt", backend_override="fixture",
    )
    validate_eig_provenance(motor_shaped_feature_ir(), result.latest.intent_graph)


def test_provenance_refuses_wrong_revision_dangling_node_and_relation():
    from pathlib import Path

    from spec2cad.pipeline import run

    example = Path(__file__).resolve().parents[1] / "examples" / "motor_adapter"
    eig = run(
        example / "sketch.png", example / "motor_datasheet.pdf",
        example / "requirement.txt", backend_override="fixture",
    ).latest.intent_graph
    document = motor_shaped_feature_ir()

    with pytest.raises(FeatureIRProvenanceError, match="does not match"):
        validate_eig_provenance(document.model_copy(update={"design_revision": 2}), eig)

    bad_link = IntentLink(eig_node_id="missing_node", relation=IntentRelation.REALIZES)
    bad_part = document.part.model_copy(update={"intent_links": (bad_link,)})
    with pytest.raises(FeatureIRProvenanceError, match="missing EIG node"):
        validate_eig_provenance(document.model_copy(update={"part": bad_part}), eig)

    wrong = IntentLink(eig_node_id="part", relation=IntentRelation.GROUPS)
    wrong_part = document.part.model_copy(update={"intent_links": (wrong,)})
    with pytest.raises(FeatureIRProvenanceError, match="requires realizes"):
        validate_eig_provenance(document.model_copy(update={"part": wrong_part}), eig)
