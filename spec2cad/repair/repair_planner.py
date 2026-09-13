"""Propose repairs for a blocked design.

Repairs are solved, not nudged: the planner rearranges the constraint to find
the value that would satisfy it, rather than stepping a parameter until the
check goes green.

Proposals are classified by what they cost you, and the classification is the
substance of the feature rather than decoration:

  SAFE    widening the plate. The part gets bigger; nothing about how it mates
          with the motor changes.

  UNSAFE  relaxing the clearance (discards a stated hard requirement) or moving
          the hole pattern (the part silently stops fitting the motor it was
          designed for -- the worst kind of failure, because it still builds,
          still validates against the altered intent, and is only discovered
          at assembly).

Only SAFE proposals can be applied in one click. UNSAFE ones are shown, with the
consequence spelled out, and require explicit acknowledgement.

Applying a repair never mutates anything; it derives the next DesignIntent
revision with full provenance.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from spec2cad.fusion.conflict_detector import minimum_plate_dimension
from spec2cad.knowledge.recommendations import recommended_rounded_width
from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.validation.gate import ReleaseDecision


class ProposalSafety(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"


class RepairProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    safety: ProposalSafety
    updates: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""
    consequence: Optional[str] = Field(
        default=None, description="what this costs you; always set for UNSAFE"
    )
    recommended: bool = False

    @property
    def auto_applicable(self) -> bool:
        """Only safe proposals may be applied without explicit acknowledgement."""
        return self.safety is ProposalSafety.SAFE


class UnsafeRepairRequiresAcknowledgement(PermissionError):
    """Raised when an unsafe proposal is applied without acknowledging it."""


def plan_repairs(
    intent: DesignIntent, decision: ReleaseDecision
) -> list[RepairProposal]:
    """Propose ways to unblock a release."""
    if decision.step_export_allowed:
        return []

    proposals: list[RepairProposal] = []

    clearance_blocked = any(
        "edge_clearance" in check.id for check in decision.blocking
    )
    if clearance_blocked:
        constraint = intent.constraint("min_hole_edge_clearance")
        if constraint is not None:
            spacing = intent.value_of("hole_spacing_x")
            hole_d = intent.value_of("mounting_hole_diameter")
            required = constraint.value
            minimum = minimum_plate_dimension(spacing, hole_d, required)
            rec = recommended_rounded_width(minimum)

            proposals.append(RepairProposal(
                id="widen_to_minimum",
                title=f"Increase plate width to {minimum:g} mm (minimum feasible)",
                safety=ProposalSafety.SAFE,
                updates={"plate_width": round(minimum, 6)},
                rationale=(
                    f"plate_width >= hole_spacing_x + hole_diameter + 2 x clearance "
                    f"= {spacing:g} + {hole_d:g} + 2 x {required:g} = {minimum:g} mm. "
                    f"This satisfies the requirement exactly, with no margin."
                ),
            ))
            proposals.append(RepairProposal(
                id="widen_to_recommended",
                title=f"Increase plate width to {rec.recommended_mm:g} mm (recommended)",
                safety=ProposalSafety.SAFE,
                updates={"plate_width": rec.recommended_mm},
                rationale=(
                    f"{rec.describe()}. Widening the plate does not change how the "
                    f"part mates with the motor."
                ),
                recommended=True,
            ))

            proposals.append(RepairProposal(
                id="relax_clearance",
                title=f"Reduce the minimum edge clearance below {required:g} mm",
                safety=ProposalSafety.UNSAFE,
                updates={},
                rationale=(
                    "the geometry would pass if the requirement were lowered to "
                    f"{_achievable_clearance(intent):.4g} mm"
                ),
                consequence=(
                    "This discards a stated hard manufacturing requirement rather than "
                    "meeting it. The thin remaining material is what the requirement "
                    "exists to prevent. Requires a decision from whoever set it."
                ),
            ))
            proposals.append(RepairProposal(
                id="change_hole_pattern",
                title="Move the mounting holes closer together",
                safety=ProposalSafety.UNSAFE,
                updates={},
                rationale="reducing hole_spacing_x would also satisfy the clearance",
                consequence=(
                    "The hole pattern is dictated by the motor datasheet. Changing it "
                    "produces a part that builds cleanly, passes every check against "
                    "the altered intent, and does not bolt to the motor. The failure "
                    "would not surface until assembly."
                ),
            ))

    return proposals


def _achievable_clearance(intent: DesignIntent) -> float:
    from spec2cad.fusion.conflict_detector import edge_clearance

    return edge_clearance(
        intent.value_of("plate_width"),
        intent.value_of("hole_spacing_x"),
        intent.value_of("mounting_hole_diameter"),
    )


def apply_repair(
    intent: DesignIntent,
    proposal: RepairProposal,
    *,
    approved_by: str,
    acknowledge_unsafe: bool = False,
) -> DesignIntent:
    """Apply a proposal by deriving the next revision.

    Refuses to apply an unsafe proposal unless the caller explicitly
    acknowledges it, so "apply the first suggestion" can never quietly move a
    motor interface.
    """
    if proposal.safety is ProposalSafety.UNSAFE and not acknowledge_unsafe:
        raise UnsafeRepairRequiresAcknowledgement(
            f"proposal {proposal.id!r} is classified unsafe and cannot be applied "
            f"automatically. {proposal.consequence or ''}".strip()
        )
    if not proposal.updates:
        raise ValueError(
            f"proposal {proposal.id!r} carries no concrete parameter change; "
            f"it describes a decision a human must make first"
        )

    return intent.derive(
        updates=proposal.updates,
        proposal_id=proposal.id,
        approved_by=approved_by,
        reason=proposal.title,
    )
