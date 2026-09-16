"""Versioned acceptance tolerances for R1 cross-backend reconciliation.

These are evidence-comparison thresholds, not CAD-kernel modeling tolerances and
not drawing/manufacturing tolerances.  A future policy change must receive a new
version so a release report always identifies the rule that authorized it.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuantityKind(str, Enum):
    DIMENSION = "dimension"
    POSITION = "position"
    VOLUME = "volume"


class ToleranceRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: Literal["mm", "mm3"]
    absolute: float = Field(ge=0, allow_inf_nan=False)
    relative: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    def allowed_error(self, reference: float) -> float:
        if not math.isfinite(reference):
            raise ValueError("reference value must be finite")
        return max(self.absolute, abs(reference) * self.relative)


class ReconciliationComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quantity: QuantityKind
    unit: Literal["mm", "mm3"]
    reference: float = Field(allow_inf_nan=False)
    observed: float = Field(allow_inf_nan=False)
    absolute_error: float = Field(ge=0, allow_inf_nan=False)
    allowed_error: float = Field(ge=0, allow_inf_nan=False)
    consistent: bool
    policy_version: str


class ReconciliationTolerancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    dimension: ToleranceRule
    position: ToleranceRule
    volume: ToleranceRule

    def rule(self, quantity: QuantityKind) -> ToleranceRule:
        return getattr(self, quantity.value)

    def compare(
        self,
        quantity: QuantityKind,
        reference: float,
        observed: float,
        *,
        unit: str,
    ) -> ReconciliationComparison:
        rule = self.rule(quantity)
        if unit != rule.unit:
            raise ValueError(
                f"{quantity.value} comparison requires {rule.unit}, got {unit}"
            )
        if not math.isfinite(reference) or not math.isfinite(observed):
            raise ValueError("reconciliation values must be finite")
        error = abs(observed - reference)
        allowed = rule.allowed_error(reference)
        # One ULP prevents a value produced by `reference + allowed` from being
        # rejected solely by its binary representation.
        consistent = error <= allowed + math.ulp(max(abs(reference), abs(observed), 1.0))
        return ReconciliationComparison(
            quantity=quantity,
            unit=rule.unit,
            reference=reference,
            observed=observed,
            absolute_error=error,
            allowed_error=allowed,
            consistent=consistent,
            policy_version=self.policy_version,
        )


R1_TOLERANCE_POLICY = ReconciliationTolerancePolicy(
    policy_version="1.0.0",
    # Cross-kernel thresholds are intentionally wider than the 1e-4 mm
    # single-kernel measurement tolerance while remaining far below any
    # governed motor-adapter dimension or clearance margin.
    dimension=ToleranceRule(unit="mm", absolute=0.01),
    position=ToleranceRule(unit="mm", absolute=0.01),
    volume=ToleranceRule(unit="mm3", absolute=0.01, relative=1e-6),
)

