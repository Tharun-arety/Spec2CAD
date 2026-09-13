"""Consolidate evidence into DesignIntent v1.

The interesting part is resolve_target(), which decides what to believe when
several sources speak to the same parameter. The rule is deliberately NOT
"highest authority wins":

    0 candidates                     -> MISSING
    1 candidate                      -> use it
    several, all agreeing            -> use it, provenance lists every source
    several, explicit vs inferred    -> the explicit annotation wins
    several explicit, disagreeing    -> ADJUDICATION_REQUIRED

That last line is the one that matters. Two sources that each state a value
outright and disagree is a question for a human, not something to settle by
consulting a precedence table. Auto-resolving it would mean silently discarding
a number a person deliberately wrote down -- and the discarded one might be the
correct one. Authority ranks candidates and orders the presentation; it never
overrules an explicit annotation on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from spec2cad.schemas.design_intent import (
    Constraint,
    ConstraintSeverity,
    DesignIntent,
    Interface,
    Parameter,
    ParameterStatus,
    PartInfo,
)
from spec2cad.schemas.evidence import Authority, Evidence, EvidenceSet, SemanticTarget

T = SemanticTarget

VALUE_TOLERANCE = 1e-6

# Radial clearance added to the motor's pilot boss so the plate drops over it.
BOSS_FIT_ALLOWANCE_MM = 0.5


@dataclass(frozen=True)
class Resolution:
    """The outcome of reconciling all evidence for one target."""

    target: SemanticTarget
    value: object
    unit: Optional[str]
    status: ParameterStatus
    provenance: list[str]
    authority: Authority
    is_explicit: bool
    competing: list[dict]
    note: str = ""


def _values_agree(a: object, b: object) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= VALUE_TOLERANCE
    return str(a).strip().lower() == str(b).strip().lower()


def resolve_target(target: SemanticTarget, candidates: list[Evidence]) -> Resolution:
    """Reconcile every piece of evidence for one target."""
    if not candidates:
        return Resolution(
            target=target, value=None, unit=None, status=ParameterStatus.MISSING,
            provenance=[], authority=Authority.ADVISORY, is_explicit=False,
            competing=[], note="no source provided this value",
        )

    if len(candidates) == 1:
        only = candidates[0]
        return Resolution(
            target=target, value=only.value, unit=only.unit,
            status=(
                ParameterStatus.CONFIRMED
                if only.is_explicit_annotation
                else ParameterStatus.INFERRED
            ),
            provenance=[only.id], authority=only.authority,
            is_explicit=only.is_explicit_annotation, competing=[],
            note=f"single source ({only.source.modality.value})",
        )

    explicit = [e for e in candidates if e.is_explicit_annotation]
    pool = explicit or candidates

    # Rank for presentation: authority first, then how sure the reader was.
    pool = sorted(pool, key=lambda e: (e.authority.rank, e.confidence), reverse=True)
    best = pool[0]

    disagreeing = [e for e in pool if not _values_agree(e.value, best.value)]

    if explicit and disagreeing:
        # Two or more sources each state a value outright and they differ.
        # This is escalated, never auto-resolved.
        competing = [
            {
                "value": e.value,
                "unit": e.unit,
                "evidence_id": e.id,
                "modality": e.source.modality.value,
                "authority": e.authority.value,
                "confidence": e.confidence,
                "raw_text": e.raw_text,
            }
            for e in pool
        ]
        return Resolution(
            target=target, value=best.value, unit=best.unit,
            status=ParameterStatus.ADJUDICATION_REQUIRED,
            provenance=[e.id for e in pool], authority=best.authority,
            is_explicit=True, competing=competing,
            note=(
                f"{len(competing)} sources state this value explicitly and disagree; "
                f"showing the highest-authority value provisionally, pending a decision"
            ),
        )

    corroborating = [e for e in candidates if _values_agree(e.value, best.value)]
    status = (
        ParameterStatus.CONFIRMED if best.is_explicit_annotation else ParameterStatus.INFERRED
    )
    note = (
        f"agreed by {len(corroborating)} sources"
        if len(corroborating) > 1
        else f"from {best.source.modality.value}"
    )
    if explicit and len(explicit) < len(candidates):
        note += "; explicit annotation preferred over inferred values"

    return Resolution(
        target=target, value=best.value, unit=best.unit, status=status,
        provenance=[e.id for e in corroborating], authority=best.authority,
        is_explicit=best.is_explicit_annotation, competing=[], note=note,
    )


def _parameter(res: Resolution, derivation: Optional[str] = None) -> Parameter:
    return Parameter(
        name=res.target.value,
        value=res.value,
        unit=res.unit,
        status=res.status,
        provenance=res.provenance,
        authority=res.authority,
        is_explicit=res.is_explicit,
        derivation=derivation or (res.note or None),
        competing_values=res.competing,
    )


# Parameters the design needs, whether or not a source supplied them.
REQUIRED_TARGETS = [
    T.PLATE_WIDTH, T.PLATE_HEIGHT, T.PLATE_THICKNESS,
    T.HOLE_SPACING_X, T.HOLE_SPACING_Y,
    T.MOUNTING_HOLE_COUNT, T.MOUNTING_HOLE_DIAMETER,
    T.MOTOR_BOSS_DIAMETER, T.EXTERNAL_CHAMFER,
]


def build_design_intent(
    evidence: EvidenceSet, part_name: str = "motor_adapter_plate"
) -> tuple[DesignIntent, list[Resolution]]:
    """Fuse evidence into DesignIntent v1, returning the resolutions too."""
    resolutions: dict[SemanticTarget, Resolution] = {}
    for target in T:
        resolutions[target] = resolve_target(target, evidence.by_target(target))

    parameters: dict[str, Parameter] = {}
    for target in REQUIRED_TARGETS:
        parameters[target.value] = _parameter(resolutions[target])

    # Derived: the plate must clear the motor's pilot boss, so the opening is
    # the boss diameter plus a fit allowance. Recorded as a derivation, not as
    # something a source stated.
    boss = resolutions[T.MOTOR_BOSS_DIAMETER]
    if isinstance(boss.value, (int, float)):
        parameters[T.SHAFT_OPENING_DIAMETER.value] = Parameter(
            name=T.SHAFT_OPENING_DIAMETER.value,
            value=round(float(boss.value) + BOSS_FIT_ALLOWANCE_MM, 4),
            unit="mm",
            status=ParameterStatus.INFERRED,
            provenance=list(boss.provenance),
            authority=Authority.DEFINITIVE,
            is_explicit=False,
            derivation=(
                f"pilot boss {boss.value} mm + {BOSS_FIT_ALLOWANCE_MM} mm fit allowance"
            ),
        )
    else:
        parameters[T.SHAFT_OPENING_DIAMETER.value] = Parameter(
            name=T.SHAFT_OPENING_DIAMETER.value, value=None,
            status=ParameterStatus.MISSING,
            derivation="requires the motor pilot boss diameter",
        )

    material = resolutions[T.MATERIAL]
    process = resolutions[T.MANUFACTURING_PROCESS]
    part = PartInfo(
        name=part_name,
        material=material.value if isinstance(material.value, str) else None,
        manufacturing_process=process.value if isinstance(process.value, str) else None,
        provenance=material.provenance + process.provenance,
    )

    interfaces: list[Interface] = []
    sx, sy = resolutions[T.HOLE_SPACING_X], resolutions[T.HOLE_SPACING_Y]
    count, dia = resolutions[T.MOUNTING_HOLE_COUNT], resolutions[T.MOUNTING_HOLE_DIAMETER]
    if all(isinstance(r.value, (int, float)) for r in (sx, sy, count, dia)):
        interfaces.append(Interface(
            name="motor_mount",
            hole_count=int(count.value),
            hole_diameter=float(dia.value),
            spacing_x=float(sx.value),
            spacing_y=float(sy.value),
            provenance=sx.provenance + sy.provenance + count.provenance + dia.provenance,
        ))

    constraints: list[Constraint] = []
    clearance = resolutions[T.MIN_HOLE_EDGE_CLEARANCE]
    if isinstance(clearance.value, (int, float)):
        constraints.append(Constraint(
            id="c_min_hole_edge_clearance",
            type="min_hole_edge_clearance",
            value=float(clearance.value),
            unit=clearance.unit or "mm",
            severity=ConstraintSeverity.HARD,
            description=(
                "minimum material between any mounting-hole edge and the plate boundary"
            ),
            provenance=clearance.provenance,
        ))

    intent = DesignIntent(
        part=part, parameters=parameters, interfaces=interfaces, constraints=constraints
    )
    return intent, [resolutions[t] for t in T]
