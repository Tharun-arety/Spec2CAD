"""Pairwise, per-quantity consistency matrices over SensorEvidence."""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from itertools import product
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.feature_ir import StableId

from .observations import Applicability
from .sensors import SensorEvidence, SensorUnit


CONSISTENCY_MATRIX_SCHEMA_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConsistencyStatus(str, Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    NOT_ASSESSED = "not_assessed"


class ComparisonKind(str, Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    NOT_ASSESSED = "not_assessed"


class ConsistencyCell(_FrozenModel):
    row_sensor_id: StableId
    column_sensor_id: StableId
    status: ConsistencyStatus
    comparison_kind: ComparisonKind
    unit: SensorUnit | None = None
    maximum_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    allowed_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result_shape(self) -> "ConsistencyCell":
        if self.comparison_kind is ComparisonKind.NOT_ASSESSED:
            if self.status is not ConsistencyStatus.NOT_ASSESSED:
                raise ValueError("unassessed comparison requires NOT_ASSESSED status")
            if self.maximum_error is not None or self.allowed_error is not None:
                raise ValueError("unassessed comparison cannot report numeric errors")
        elif self.status is ConsistencyStatus.NOT_ASSESSED:
            raise ValueError("assessed comparison cannot report NOT_ASSESSED")
        elif self.comparison_kind is ComparisonKind.NUMERIC:
            if self.maximum_error is None or self.allowed_error is None:
                raise ValueError("numeric comparison requires error and tolerance")
            if self.unit is None:
                raise ValueError("numeric comparison requires a unit")
        elif self.maximum_error is not None or self.allowed_error is not None:
            raise ValueError("categorical comparison cannot report numeric errors")
        return self


class QuantityConsistencyMatrix(_FrozenModel):
    schema_version: Literal["1.0.0"] = CONSISTENCY_MATRIX_SCHEMA_VERSION
    id: StableId
    design_revision: int = Field(ge=1)
    quantity: StableId
    sensor_ids: tuple[StableId, ...] = Field(min_length=1)
    cells: tuple[ConsistencyCell, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_matrix(self) -> "QuantityConsistencyMatrix":
        if len(self.sensor_ids) != len(set(self.sensor_ids)):
            raise ValueError("matrix sensor ids must be unique")
        expected = set(product(self.sensor_ids, repeat=2))
        pairs = [(item.row_sensor_id, item.column_sensor_id) for item in self.cells]
        if len(pairs) != len(set(pairs)) or set(pairs) != expected:
            raise ValueError("matrix must contain exactly one cell for every sensor pair")
        by_pair = {
            (item.row_sensor_id, item.column_sensor_id): item for item in self.cells
        }
        for left, right in expected:
            forward = by_pair[(left, right)]
            reverse = by_pair[(right, left)]
            if (
                forward.status != reverse.status
                or forward.comparison_kind != reverse.comparison_kind
                or forward.unit != reverse.unit
                or forward.maximum_error != reverse.maximum_error
                or forward.allowed_error != reverse.allowed_error
            ):
                raise ValueError("matrix comparisons must be symmetric")
        return self

    def cell(self, row_sensor_id: str, column_sensor_id: str) -> ConsistencyCell:
        for item in self.cells:
            if (
                item.row_sensor_id == row_sensor_id
                and item.column_sensor_id == column_sensor_id
            ):
                return item
        raise KeyError(f"no matrix cell for {row_sensor_id!r}, {column_sensor_id!r}")


def _not_assessed(left: SensorEvidence, right: SensorEvidence, detail: str):
    return ConsistencyStatus.NOT_ASSESSED, ComparisonKind.NOT_ASSESSED, None, None, None, detail


def _compare(left: SensorEvidence, right: SensorEvidence):
    if (
        left.applicability is not Applicability.APPLICABLE
        or right.applicability is not Applicability.APPLICABLE
    ):
        return _not_assessed(left, right, "one or both sensors are unavailable")
    if left.unit != right.unit:
        return _not_assessed(left, right, "sensor units are incompatible")

    left_categorical = isinstance(left.value, (bool, str))
    right_categorical = isinstance(right.value, (bool, str))
    if left_categorical != right_categorical:
        return _not_assessed(left, right, "sensor reading types are incompatible")
    if left_categorical:
        consistent = left.value == right.value
        return (
            ConsistencyStatus.CONSISTENT if consistent else ConsistencyStatus.INCONSISTENT,
            ComparisonKind.CATEGORICAL,
            left.unit,
            None,
            None,
            "categorical readings match" if consistent else "categorical readings differ",
        )

    if left.tolerance is None or right.tolerance is None:
        return _not_assessed(left, right, "numeric comparison lacks declared tolerance")
    left_values = left.value if isinstance(left.value, tuple) else (left.value,)
    right_values = right.value if isinstance(right.value, tuple) else (right.value,)
    if len(left_values) != len(right_values):
        return _not_assessed(left, right, "numeric reading shapes are incompatible")

    maximum_error = max(
        abs(left_value - right_value)
        for left_value, right_value in zip(left_values, right_values)
    )
    magnitude = max(
        (abs(value) for value in (*left_values, *right_values)),
        default=0.0,
    )
    allowed_error = min(
        max(tolerance.absolute, magnitude * tolerance.relative)
        for tolerance in (left.tolerance, right.tolerance)
    )
    consistent = maximum_error <= allowed_error + math.ulp(
        max(magnitude, allowed_error, 1.0)
    )
    return (
        ConsistencyStatus.CONSISTENT if consistent else ConsistencyStatus.INCONSISTENT,
        ComparisonKind.NUMERIC,
        left.unit,
        maximum_error,
        allowed_error,
        (
            f"maximum error {maximum_error:.9g} is within {allowed_error:.9g}"
            if consistent
            else f"maximum error {maximum_error:.9g} exceeds {allowed_error:.9g}"
        ),
    )


def build_consistency_matrices(
    evidence: tuple[SensorEvidence, ...],
) -> tuple[QuantityConsistencyMatrix, ...]:
    """Group one design revision and compare every sensor pair per quantity."""
    if not evidence:
        raise ValueError("at least one SensorEvidence record is required")
    evidence_ids = [item.id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("SensorEvidence ids must be unique")
    revisions = {item.design_revision for item in evidence}
    if len(revisions) != 1:
        raise ValueError("all SensorEvidence must use the same design revision")
    design_revision = revisions.pop()

    by_quantity: dict[str, list[SensorEvidence]] = defaultdict(list)
    for item in evidence:
        by_quantity[item.quantity].append(item)

    matrices = []
    for quantity in sorted(by_quantity):
        sensors = sorted(by_quantity[quantity], key=lambda item: item.id)
        cells = []
        for left, right in product(sensors, repeat=2):
            status, kind, unit, error, allowed, detail = _compare(left, right)
            cells.append(ConsistencyCell(
                row_sensor_id=left.id,
                column_sensor_id=right.id,
                status=status,
                comparison_kind=kind,
                unit=unit,
                maximum_error=error,
                allowed_error=allowed,
                detail=detail,
            ))
        matrices.append(QuantityConsistencyMatrix(
            id=f"matrix.{quantity}.r{design_revision}",
            design_revision=design_revision,
            quantity=quantity,
            sensor_ids=tuple(item.id for item in sensors),
            cells=tuple(cells),
        ))
    return tuple(matrices)
