"""Reconciliation observations preserve layer, applicability and authority."""

import pytest
from pydantic import ValidationError

from spec2cad.reconciliation import (
    Applicability,
    GovernedQuantity,
    InterfaceGeometryObservation,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    ObservationSource,
    ObservationUnit,
    Point2D,
    PointSetObservation,
    PredicateObservation,
    PredicateOutcome,
)


HASH = "a" * 64


def source(layer, name, backend=None):
    return ObservationSource(
        layer=layer,
        document_id=f"document.{name}",
        document_sha256=HASH,
        backend_id=backend,
        backend_version="1.0" if backend else None,
    )


def test_same_quantity_is_distinct_across_all_four_evidence_layers():
    observations = tuple(
        NumericObservation(
            id=f"observation.width.{layer.value}",
            quantity=GovernedQuantity.PLATE_WIDTH,
            source=source(
                layer, layer.value,
                "freecad" if layer in {
                    ObservationLayer.NATIVE_STATE,
                    ObservationLayer.BREP_MEASUREMENT,
                } else None,
            ),
            method={
                ObservationLayer.ENGINEERING_INTENT: "resolved EIG dimension",
                ObservationLayer.FEATURE_IR: "Feature IR parameter",
                ObservationLayer.NATIVE_STATE: "native spreadsheet value",
                ObservationLayer.BREP_MEASUREMENT: "planar face extent",
            }[layer],
            governing=layer in {
                ObservationLayer.NATIVE_STATE,
                ObservationLayer.BREP_MEASUREMENT,
            },
            value=45.0,
            unit=ObservationUnit.MILLIMETRE,
        )
        for layer in ObservationLayer
    )
    bundle = ObservationSet(
        id="observations.motor.r2",
        design_revision=2,
        feature_ir_sha256=HASH,
        observations=observations,
    )
    assert ObservationSet.model_validate_json(bundle.model_dump_json()) == bundle
    assert {item.source.layer for item in bundle.observations} == set(ObservationLayer)


def test_points_interface_and_predicate_are_closed_typed_observations():
    measured = source(ObservationLayer.BREP_MEASUREMENT, "freecad_brep", "freecad")
    points = tuple(Point2D(x_mm=x, y_mm=y) for x in (-15.5, 15.5) for y in (-15.5, 15.5))
    point_set = PointSetObservation(
        id="observation.mounting_centers.freecad",
        source=measured,
        method="cylindrical surface axes",
        governing=True,
        points=points,
    )
    interface = InterfaceGeometryObservation(
        id="observation.interface.freecad",
        source=measured,
        method="semantic interface surfaces",
        governing=True,
        opening_diameter_mm=22.5,
        mounting_diameter_mm=3.4,
        mounting_centers=points,
    )
    predicate = PredicateObservation(
        id="observation.predicate.clearance.freecad",
        source=measured,
        method="compiled requirement predicate",
        governing=True,
        requirement_id="req_min_edge_clearance",
        outcome=PredicateOutcome.PASS,
        measured_value=5.3,
        threshold=4.0,
    )
    assert point_set.quantity is GovernedQuantity.MOUNTING_HOLE_CENTERS
    assert interface.quantity is GovernedQuantity.INTERFACE_GEOMETRY
    assert predicate.quantity is GovernedQuantity.REQUIREMENT_PREDICATE


def test_unavailable_observation_has_no_value_and_cannot_govern():
    unavailable = NumericObservation(
        id="observation.volume.unsupported",
        quantity=GovernedQuantity.VOLUME,
        source=source(ObservationLayer.NATIVE_STATE, "cadquery", "cadquery"),
        applicability=Applicability.UNSUPPORTED,
        method="native mass property lookup",
        governing=False,
        reason="CadQuery has no native document property",
        value=None,
        unit=ObservationUnit.CUBIC_MILLIMETRE,
    )
    assert unavailable.value is None
    with pytest.raises(ValidationError, match="cannot govern"):
        NumericObservation.model_validate({
            **unavailable.model_dump(), "governing": True
        })
    with pytest.raises(ValidationError, match="exactly when applicable"):
        NumericObservation.model_validate({
            **unavailable.model_dump(), "value": 1.0, "governing": False
        })


def test_intent_and_feature_ir_values_cannot_claim_release_authority():
    for layer in (ObservationLayer.ENGINEERING_INTENT, ObservationLayer.FEATURE_IR):
        with pytest.raises(ValidationError, match="cannot govern"):
            NumericObservation(
                id=f"observation.width.{layer.value}",
                quantity="plate_width",
                source=source(layer, layer.value),
                method="planned value",
                governing=True,
                value=45.0,
                unit="mm",
            )


def test_backend_identity_and_units_fail_closed():
    with pytest.raises(ValidationError, match="backend layers require"):
        source(ObservationLayer.BREP_MEASUREMENT, "missing_backend")
    with pytest.raises(ValidationError, match="requires unit mm3"):
        NumericObservation(
            id="observation.volume.bad_unit",
            quantity="volume",
            source=source(ObservationLayer.BREP_MEASUREMENT, "freecad", "freecad"),
            method="solid volume",
            value=1.0,
            unit="mm",
        )
