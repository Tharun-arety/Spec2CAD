"""Fail-closed classification of the complete R1 reconciliation result."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .geometry import GeometryReconciliationReport
from .observations import (
    Applicability,
    GovernedQuantity,
    InterfaceGeometryObservation,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    PointSetObservation,
)
from .predicates import PredicateReconciliationReport
from .tolerances import QuantityKind, R1_TOLERANCE_POLICY


class ReconciliationClassification(str, Enum):
    CONSISTENT = "CONSISTENT"
    PIPELINE_DEFECT = "PIPELINE_DEFECT"
    BACKEND_DIVERGENCE = "BACKEND_DIVERGENCE"
    SENSOR_DISAGREEMENT = "SENSOR_DISAGREEMENT"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_ASSESSED = "NOT_ASSESSED"


class ClassifiedReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    feature_ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: ReconciliationClassification
    governing: bool
    reasons: tuple[str, ...] = Field(min_length=1)

    @property
    def release_consistent(self) -> bool:
        return (
            self.governing
            and self.classification is ReconciliationClassification.CONSISTENT
        )


def _brep_availability(observations: ObservationSet) -> tuple[bool, bool]:
    records = [
        item for item in observations.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
    ]
    unsupported = any(item.applicability is Applicability.UNSUPPORTED for item in records)
    not_assessed = not records or any(
        item.applicability is Applicability.NOT_ASSESSED for item in records
    )
    return unsupported, not_assessed


def _numeric_kind(quantity: GovernedQuantity) -> QuantityKind:
    if quantity is GovernedQuantity.VOLUME:
        return QuantityKind.VOLUME
    return QuantityKind.DIMENSION


def _sensor_disagreements(observations: ObservationSet) -> tuple[str, ...]:
    """Compare applicable native records with matching measured B-Rep records."""
    reasons: list[str] = []
    native = {
        (item.quantity, item.kind): item for item in observations.observations
        if item.source.layer is ObservationLayer.NATIVE_STATE
        and item.applicability is Applicability.APPLICABLE
    }
    measured = {
        (item.quantity, item.kind): item for item in observations.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
        and item.applicability is Applicability.APPLICABLE
    }
    for key, left in native.items():
        right = measured.get(key)
        if right is None:
            continue
        if isinstance(left, NumericObservation) and isinstance(right, NumericObservation):
            comparison = R1_TOLERANCE_POLICY.compare(
                _numeric_kind(left.quantity), left.value, right.value,
                unit=left.unit.value,
            )
            if not comparison.consistent:
                reasons.append(f"{observations.id}: native/B-Rep {left.quantity.value} disagree")
        elif isinstance(left, PointSetObservation) and isinstance(right, PointSetObservation):
            if len(left.points) != len(right.points):
                reasons.append(f"{observations.id}: native/B-Rep hole counts disagree")
                continue
            errors = [
                max(abs(a.x_mm - b.x_mm), abs(a.y_mm - b.y_mm))
                for a, b in zip(sorted(left.points, key=lambda p: (p.x_mm, p.y_mm)),
                                sorted(right.points, key=lambda p: (p.x_mm, p.y_mm)))
            ]
            if any(error > R1_TOLERANCE_POLICY.position.absolute for error in errors):
                reasons.append(f"{observations.id}: native/B-Rep hole centers disagree")
        elif (
            isinstance(left, InterfaceGeometryObservation)
            and isinstance(right, InterfaceGeometryObservation)
        ):
            values = (
                (left.opening_diameter_mm, right.opening_diameter_mm),
                (left.mounting_diameter_mm, right.mounting_diameter_mm),
            )
            if any(
                not R1_TOLERANCE_POLICY.compare(
                    QuantityKind.DIMENSION, expected, observed, unit="mm"
                ).consistent
                for expected, observed in values
            ):
                reasons.append(f"{observations.id}: native/B-Rep interface geometry disagrees")
    return tuple(reasons)


def classify_reconciliation(
    left: ObservationSet,
    right: ObservationSet,
    geometry: GeometryReconciliationReport | None,
    predicates: PredicateReconciliationReport | None,
) -> ClassifiedReconciliation:
    identity = left.feature_ir_sha256
    if left.feature_ir_sha256 != right.feature_ir_sha256 or any(
        report is not None and report.feature_ir_sha256 != identity
        for report in (geometry, predicates)
    ):
        return ClassifiedReconciliation(
            feature_ir_sha256=identity,
            classification=ReconciliationClassification.PIPELINE_DEFECT,
            governing=True,
            reasons=("Feature IR identity is inconsistent across pipeline evidence",),
        )

    availability = [_brep_availability(item) for item in (left, right)]
    if any(unsupported for unsupported, _ in availability):
        return ClassifiedReconciliation(
            feature_ir_sha256=identity,
            classification=ReconciliationClassification.UNSUPPORTED,
            governing=True,
            reasons=("a required B-Rep observation is explicitly unsupported",),
        )
    if geometry is None or predicates is None or any(
        not_assessed for _, not_assessed in availability
    ):
        return ClassifiedReconciliation(
            feature_ir_sha256=identity,
            classification=ReconciliationClassification.NOT_ASSESSED,
            governing=True,
            reasons=("required reconciliation evidence has not been assessed",),
        )

    sensor_reasons = (
        *_sensor_disagreements(left), *_sensor_disagreements(right),
    )
    if sensor_reasons:
        return ClassifiedReconciliation(
            feature_ir_sha256=identity,
            classification=ReconciliationClassification.SENSOR_DISAGREEMENT,
            governing=True,
            reasons=sensor_reasons,
        )
    if not geometry.consistent or not predicates.consistent:
        return ClassifiedReconciliation(
            feature_ir_sha256=identity,
            classification=ReconciliationClassification.BACKEND_DIVERGENCE,
            governing=True,
            reasons=("governing backend observations do not agree",),
        )
    return ClassifiedReconciliation(
        feature_ir_sha256=identity,
        classification=ReconciliationClassification.CONSISTENT,
        governing=True,
        reasons=("all governed observations and predicate outcomes agree",),
    )
