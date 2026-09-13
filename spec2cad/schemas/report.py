"""Shared result shapes for preflight and measured validation.

Both stages emit the same CheckResult type on purpose. Preflight *predicts* a
value symbolically from DesignIntent; measured validation *observes* it on the
finished solid. Because they speak the same language, the two can be compared
directly -- and a disagreement between a prediction and a measurement is itself
a bug worth failing a test over, rather than something that quietly passes
because only one of them ran.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIPPED = "skipped"     # could not run, e.g. a prerequisite was missing


class CheckStage(str, Enum):
    SCHEMA = "schema"
    PREFLIGHT = "preflight"           # symbolic, advisory, pre-geometry
    TOPOLOGY = "topology"             # measured on the B-Rep
    DIMENSIONAL = "dimensional"       # measured on the B-Rep
    REQUIREMENT = "requirement"       # measured, against a stated constraint


class ConflictClass(str, Enum):
    """Why a check failed. These are not interchangeable.

    SOURCE means two sources explicitly disagree about the same thing -- a
    question for a human about which document is right.

    CONSTRAINT means every value is individually trusted and correctly read,
    but together they cannot be satisfied. Nobody misread anything; the design
    as specified is impossible. Blaming a source here would be wrong, so these
    are attributed to the responsible *parameters* instead.
    """

    SOURCE = "source_conflict"
    CONSTRAINT = "constraint_conflict"
    COMPLETENESS = "completeness"
    EXECUTION = "execution"


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    stage: CheckStage
    name: str
    status: CheckStatus

    expected: Optional[str] = None
    actual: Optional[str] = None

    required_value: Optional[float] = None
    measured_value: Optional[float] = None
    tolerance: Optional[float] = None

    conflict_class: Optional[ConflictClass] = None
    responsible_parameters: list[str] = Field(default_factory=list)
    message: str = ""

    @property
    def failed(self) -> bool:
        return self.status is CheckStatus.FAIL


class Report(BaseModel):
    """A set of check results from one stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: CheckStage
    design_revision: int
    checks: list[CheckResult] = Field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is CheckStatus.FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is CheckStatus.WARN]

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def responsible_parameters(self) -> list[str]:
        names: list[str] = []
        for check in self.failures:
            for p in check.responsible_parameters:
                if p not in names:
                    names.append(p)
        return names

    def get(self, check_id: str) -> Optional[CheckResult]:
        return next((c for c in self.checks if c.id == check_id), None)

    def summary(self) -> str:
        n_pass = sum(1 for c in self.checks if c.status is CheckStatus.PASS)
        return (
            f"{self.stage.value}: {n_pass}/{len(self.checks)} passed, "
            f"{len(self.failures)} failed, {len(self.warnings)} warnings"
        )
