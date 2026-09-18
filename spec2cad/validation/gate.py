"""The release gate: the only thing in the system that can block an export.

Separating this from generation is the whole point of the architecture. Earlier
drafts blocked *execution* when a constraint failed, which sounds safer but is
strictly worse: refusing to build means the violation can only ever be
predicted, never measured. Here the invalid candidate is built and measured --
so the report says "2.8 mm, measured on the solid" rather than "2.8 mm,
calculated from the inputs" -- and then the gate refuses to release it.

Consequences of a refusal:
  * STEP export is withheld (the manufacturing artifact)
  * the viewer mesh is still available, marked PROVISIONAL, so a human can see
    what the conflict actually looks like
  * repair proposals are offered
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)
from spec2cad.reconciliation.classification import ClassifiedReconciliation
from spec2cad.reconciliation.governing_consistency import (
    GoverningConsistencyAssessment,
)

PROVISIONAL_WATERMARK = "PROVISIONAL - NOT FOR MANUFACTURE"


class ReleaseStatus(str, Enum):
    AUTHORISED = "authorised"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ReleaseDecision:
    status: ReleaseStatus
    design_revision: int
    blocking: list[CheckResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def step_export_allowed(self) -> bool:
        return self.status is ReleaseStatus.AUTHORISED

    @property
    def mesh_watermark(self) -> str | None:
        return None if self.step_export_allowed else PROVISIONAL_WATERMARK

    @property
    def responsible_parameters(self) -> list[str]:
        names: list[str] = []
        for check in self.blocking:
            for p in check.responsible_parameters:
                if p not in names:
                    names.append(p)
        return names

    def explain(self) -> str:
        if self.step_export_allowed:
            return (
                f"Release authorised for DesignIntent v{self.design_revision}: "
                f"every hard requirement is satisfied by the measured geometry."
            )
        lines = [
            f"Release BLOCKED for DesignIntent v{self.design_revision}. "
            f"STEP export is withheld.",
        ]
        lines.extend(f"  - {r}" for r in self.reasons)
        return "\n".join(lines)


def evaluate_release(
    intent: DesignIntent,
    measured_reports: list[Report],
    *,
    governing_reconciliation: ClassifiedReconciliation | None = None,
    governing_consistency: GoverningConsistencyAssessment | None = None,
) -> ReleaseDecision:
    """Decide whether the measured geometry may be released.

    Acts ONLY on measured reports. Preflight predictions are deliberately not
    accepted here -- a prediction is not evidence about the artifact.
    """
    blocking: list[CheckResult] = []
    reasons: list[str] = []

    for report in measured_reports:
        for check in report.checks:
            if check.status is not CheckStatus.FAIL:
                continue
            blocking.append(check)
            reasons.append(check.message or check.name)

    # A design still carrying an unresolved source disagreement is not
    # releasable either, even if the provisional value happens to build.
    disputed = [
        name for name, p in intent.parameters.items()
        if p.competing_values
    ]
    for name in disputed:
        reasons.append(
            f"{name} is still disputed between sources and has not been adjudicated"
        )
        blocking.append(CheckResult(
            id=f"gate_disputed_{name}",
            stage=CheckStage.SCHEMA,
            name=f"{name} adjudicated",
            status=CheckStatus.FAIL,
            conflict_class=ConflictClass.SOURCE,
            responsible_parameters=[name],
            message=f"{name} has competing explicit values that no one has decided between",
        ))

    if (
        governing_reconciliation is not None
        and governing_reconciliation.governing
        and not governing_reconciliation.release_consistent
    ):
        classification = governing_reconciliation.classification.value
        message = (
            f"cross-backend reconciliation classified {classification}: "
            + "; ".join(governing_reconciliation.reasons)
        )
        reasons.append(message)
        blocking.append(CheckResult(
            id="gate_cross_backend_reconciliation",
            stage=CheckStage.REQUIREMENT,
            name="governing cross-backend reconciliation",
            status=CheckStatus.FAIL,
            expected="CONSISTENT",
            actual=classification,
            conflict_class=ConflictClass.EXECUTION,
            message=message,
        ))

    if governing_consistency is not None and governing_consistency.governing:
        revision_matches = governing_consistency.design_revision == intent.revision
        status_value = (
            governing_consistency.status.value
            if revision_matches else "revision_mismatch"
        )
        message = (
            f"governing sensor consistency is {status_value}: "
            + (
                "; ".join(governing_consistency.reasons)
                if revision_matches
                else (
                    f"assessment revision {governing_consistency.design_revision} "
                    f"does not match intent revision {intent.revision}"
                )
            )
        )
        if revision_matches and governing_consistency.release_consistent:
            message = ""
        if message:
            reasons.append(message)
            blocking.append(CheckResult(
                id="gate_sensor_consistency",
                stage=CheckStage.REQUIREMENT,
                name="governing sensor consistency",
                status=CheckStatus.FAIL,
                expected="consistent",
                actual=status_value,
                conflict_class=ConflictClass.EXECUTION,
                message=message,
            ))

    status = ReleaseStatus.BLOCKED if blocking else ReleaseStatus.AUTHORISED
    return ReleaseDecision(
        status=status,
        design_revision=intent.revision,
        blocking=blocking,
        reasons=reasons,
    )
