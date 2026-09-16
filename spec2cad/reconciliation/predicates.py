"""Execute and compare compiled requirements using measured observations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.intent_graph import EngineeringIntentGraph
from spec2cad.schemas.requirement_ir import MinimumDistancePredicate
from spec2cad.validation.predicate_compiler import compile_requirement_predicates

from .geometry import GeometryReconciliationError
from .observations import (
    Applicability,
    GovernedQuantity,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    PointSetObservation,
    PredicateObservation,
    PredicateOutcome,
)


class PredicateParityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    left_observation_id: str
    right_observation_id: str
    left_outcome: PredicateOutcome
    right_outcome: PredicateOutcome
    left_measured_value: float = Field(allow_inf_nan=False)
    right_measured_value: float = Field(allow_inf_nan=False)
    threshold: float = Field(allow_inf_nan=False)
    identical: bool


class PredicateReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    feature_ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[PredicateParityCheck, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> "PredicateReconciliationReport":
        ids = [item.requirement_id for item in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("predicate requirements must be unique")
        return self

    @property
    def consistent(self) -> bool:
        return all(item.identical for item in self.checks)


def _measured(observations: ObservationSet, quantity, cls):
    matches = [
        item for item in observations.observations
        if isinstance(item, cls)
        and item.source.layer is ObservationLayer.BREP_MEASUREMENT
        and item.quantity is quantity
        and item.applicability is Applicability.APPLICABLE
    ]
    if len(matches) != 1:
        raise GeometryReconciliationError(f"missing measured {quantity.value}")
    return matches[0]


def observe_requirement_predicates(
    observations: ObservationSet,
    intent_graph: EngineeringIntentGraph,
) -> tuple[PredicateObservation, ...]:
    program = compile_requirement_predicates(intent_graph)
    width = _measured(
        observations, GovernedQuantity.PLATE_WIDTH, NumericObservation
    )
    height = _measured(
        observations, GovernedQuantity.PLATE_HEIGHT, NumericObservation
    )
    diameter = _measured(
        observations, GovernedQuantity.MOUNTING_DIAMETER, NumericObservation
    )
    centers = _measured(
        observations, GovernedQuantity.MOUNTING_HOLE_CENTERS, PointSetObservation
    )
    results = []
    for predicate in program.predicates:
        if not isinstance(predicate, MinimumDistancePredicate):
            raise GeometryReconciliationError(
                f"unsupported requirement predicate {predicate.type!r}"
            )
        radius = diameter.value / 2
        clearance = min(
            min(
                width.value / 2 - (abs(point.x_mm) + radius),
                height.value / 2 - (abs(point.y_mm) + radius),
            )
            for point in centers.points
        )
        source = width.source
        results.append(PredicateObservation(
            id=f"observation.{source.backend_id}.predicate.{predicate.source_requirement_id}",
            source=source,
            method="compiled minimum-distance predicate over measured B-Rep observations",
            governing=True,
            related_record_ids=(
                width.id, height.id, diameter.id, centers.id, predicate.source_requirement_id,
            ),
            requirement_id=predicate.source_requirement_id,
            outcome=(
                PredicateOutcome.PASS
                if clearance >= predicate.threshold - 1e-9
                else PredicateOutcome.FAIL
            ),
            measured_value=clearance,
            threshold=predicate.threshold,
        ))
    return tuple(results)


def reconcile_predicates(
    left: tuple[PredicateObservation, ...],
    right: tuple[PredicateObservation, ...],
    *,
    feature_ir_sha256: str,
) -> PredicateReconciliationReport:
    left_by_id = {item.requirement_id: item for item in left}
    right_by_id = {item.requirement_id: item for item in right}
    if not left_by_id or set(left_by_id) != set(right_by_id):
        raise GeometryReconciliationError("predicate requirement IDs differ")
    checks = []
    for requirement_id in sorted(left_by_id):
        left_item, right_item = left_by_id[requirement_id], right_by_id[requirement_id]
        if left_item.threshold != right_item.threshold:
            raise GeometryReconciliationError("predicate thresholds differ")
        checks.append(PredicateParityCheck(
            requirement_id=requirement_id,
            left_observation_id=left_item.id,
            right_observation_id=right_item.id,
            left_outcome=left_item.outcome,
            right_outcome=right_item.outcome,
            left_measured_value=left_item.measured_value,
            right_measured_value=right_item.measured_value,
            threshold=left_item.threshold,
            identical=left_item.outcome is right_item.outcome,
        ))
    return PredicateReconciliationReport(
        feature_ir_sha256=feature_ir_sha256,
        checks=tuple(checks),
    )
