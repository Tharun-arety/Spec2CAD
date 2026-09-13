"""Preflight: predict constraint violations symbolically, before any geometry.

Preflight is ADVISORY. It never blocks. Its job is to predict cheaply what the
measured validation will later observe on the real solid, so that:

  - the user sees the problem immediately, without waiting for a CAD build, and
  - a disagreement between what preflight predicted and what the finished solid
    actually measures is detectable, and is treated as a bug in one of them.

Only the release gate blocks, and it acts on measurements, never on these
predictions.
"""

from __future__ import annotations

import math
from typing import Optional

from spec2cad.schemas.design_intent import ConstraintSeverity, DesignIntent, ParameterStatus
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)

# Parameters that jointly determine hole-to-edge clearance.
CLEARANCE_PARAMETERS = ["plate_width", "hole_spacing_x", "mounting_hole_diameter"]


def edge_clearance(plate_dim: float, spacing: float, hole_diameter: float) -> float:
    """Material between a mounting-hole edge and the nearest plate boundary.

        (plate_dim - spacing) / 2   distance from hole centre to the boundary
        - hole_diameter / 2         less the hole's own radius
    """
    return (plate_dim - spacing) / 2.0 - hole_diameter / 2.0


def minimum_plate_dimension(
    spacing: float, hole_diameter: float, required_clearance: float
) -> float:
    """Smallest plate dimension that satisfies the clearance requirement.

    Rearranged from edge_clearance() for the plate dimension:
        spacing + hole_diameter + 2 * required_clearance
    """
    return spacing + hole_diameter + 2.0 * required_clearance


def _missing(intent: DesignIntent, *names: str) -> list[str]:
    return [n for n in names if not intent.has(n)]


def run_preflight(intent: DesignIntent) -> Report:
    """Evaluate every constraint symbolically against DesignIntent."""
    checks: list[CheckResult] = []

    # ---- completeness ----------------------------------------------------
    missing = intent.missing_parameters
    checks.append(CheckResult(
        id="pre_completeness",
        stage=CheckStage.PREFLIGHT,
        name="All required parameters present",
        status=CheckStatus.PASS if not missing else CheckStatus.FAIL,
        expected="no missing parameters",
        actual="none missing" if not missing else f"missing: {', '.join(missing)}",
        conflict_class=None if not missing else ConflictClass.COMPLETENESS,
        responsible_parameters=missing,
        message=(
            "every parameter the design needs has a value"
            if not missing
            else f"{len(missing)} parameter(s) were not supplied by any source"
        ),
    ))

    # ---- source conflicts (distinct from constraint conflicts) -----------
    disputed = [
        name for name, p in intent.parameters.items()
        if p.status is ParameterStatus.ADJUDICATION_REQUIRED
    ]
    for name in disputed:
        p = intent.param(name)
        values = ", ".join(
            f"{c['value']} ({c['modality']})" for c in p.competing_values
        )
        checks.append(CheckResult(
            id=f"pre_source_conflict_{name}",
            stage=CheckStage.PREFLIGHT,
            name=f"Sources agree on {name}",
            status=CheckStatus.FAIL,
            expected="one agreed value",
            actual=values,
            conflict_class=ConflictClass.SOURCE,
            responsible_parameters=[name],
            message=(
                f"{name} is stated explicitly by more than one source with different "
                f"values ({values}). This needs a human decision about which document "
                f"is correct; it is not resolved by source precedence."
            ),
        ))
    if not disputed:
        checks.append(CheckResult(
            id="pre_source_conflicts",
            stage=CheckStage.PREFLIGHT,
            name="Sources agree on every parameter",
            status=CheckStatus.PASS,
            expected="no explicit disagreements",
            actual="none",
            message="no two sources explicitly state different values for the same parameter",
        ))

    # ---- hole-to-edge clearance -----------------------------------------
    constraint = intent.constraint("min_hole_edge_clearance")
    if constraint is None:
        checks.append(CheckResult(
            id="pre_edge_clearance", stage=CheckStage.PREFLIGHT,
            name="Minimum hole edge clearance", status=CheckStatus.SKIPPED,
            message="no edge-clearance constraint was stated",
        ))
    else:
        for axis, plate_param, spacing_param in (
            ("x", "plate_width", "hole_spacing_x"),
            ("y", "plate_height", "hole_spacing_y"),
        ):
            absent = _missing(intent, plate_param, spacing_param, "mounting_hole_diameter")
            if absent:
                checks.append(CheckResult(
                    id=f"pre_edge_clearance_{axis}", stage=CheckStage.PREFLIGHT,
                    name=f"Hole edge clearance ({axis})", status=CheckStatus.SKIPPED,
                    responsible_parameters=absent,
                    message=f"cannot evaluate: missing {', '.join(absent)}",
                ))
                continue

            plate_dim = intent.value_of(plate_param)
            spacing = intent.value_of(spacing_param)
            hole_d = intent.value_of("mounting_hole_diameter")
            actual = edge_clearance(plate_dim, spacing, hole_d)
            required = constraint.value
            ok = actual >= required - 1e-9

            needed = minimum_plate_dimension(spacing, hole_d, required)
            checks.append(CheckResult(
                id=f"pre_edge_clearance_{axis}",
                stage=CheckStage.PREFLIGHT,
                name=f"Hole edge clearance ({axis})",
                status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                expected=f">= {required:g} mm",
                actual=f"{actual:.4g} mm",
                required_value=required,
                measured_value=round(actual, 6),
                conflict_class=None if ok else ConflictClass.CONSTRAINT,
                responsible_parameters=(
                    [] if ok else [plate_param, spacing_param, "mounting_hole_diameter"]
                ),
                message=(
                    f"{actual:.4g} mm of material between hole edge and boundary"
                    if ok else
                    f"the {plate_dim:g} mm {plate_param.replace('_', ' ')} conflicts with the "
                    f"{spacing:g} mm hole pattern and the required {required:g} mm edge "
                    f"clearance: only {actual:.4g} mm is available. "
                    f"The minimum feasible {plate_param.replace('_', ' ')} is {needed:g} mm."
                ),
            ))

    # ---- chamfer feasibility --------------------------------------------
    # NOTE: an earlier draft checked chamfer against plate THICKNESS. That rule
    # is wrong and was removed. These chamfers run along the external VERTICAL
    # edges, so thickness does not limit them at all -- a 1 mm chamfer on a
    # 1.5 mm plate builds a perfectly valid solid (verified against the kernel).
    # The real limit is in-plane: the chamfer cannot consume half the plate, and
    # it must not eat into a mounting hole.
    absent = _missing(intent, "external_chamfer", "plate_width", "plate_height")
    if absent:
        checks.append(CheckResult(
            id="pre_chamfer", stage=CheckStage.PREFLIGHT, name="Chamfer feasibility",
            status=CheckStatus.SKIPPED, responsible_parameters=absent,
            message=f"cannot evaluate: missing {', '.join(absent)}",
        ))
    else:
        chamfer = intent.value_of("external_chamfer")
        smallest = min(intent.value_of("plate_width"), intent.value_of("plate_height"))
        limit = smallest / 2.0
        ok = chamfer < limit
        checks.append(CheckResult(
            id="pre_chamfer",
            stage=CheckStage.PREFLIGHT,
            name="Chamfer fits in plane",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            expected=f"< {limit:g} mm (half the smallest in-plane dimension)",
            actual=f"{chamfer:g} mm",
            required_value=limit,
            measured_value=chamfer,
            conflict_class=None if ok else ConflictClass.CONSTRAINT,
            responsible_parameters=(
                [] if ok else ["external_chamfer", "plate_width", "plate_height"]
            ),
            message=(
                f"{chamfer:g} mm chamfer is within the in-plane limit"
                if ok else
                f"a {chamfer:g} mm chamfer cannot be cut on a plate whose smallest "
                f"in-plane dimension is {smallest:g} mm"
            ),
        ))

    # ---- shaft opening must not break into the mounting holes ------------
    absent = _missing(
        intent, "shaft_opening_diameter", "hole_spacing_x",
        "hole_spacing_y", "mounting_hole_diameter",
    )
    if absent:
        checks.append(CheckResult(
            id="pre_hole_overlap", stage=CheckStage.PREFLIGHT,
            name="Shaft opening clears mounting holes", status=CheckStatus.SKIPPED,
            responsible_parameters=absent,
            message=f"cannot evaluate: missing {', '.join(absent)}",
        ))
    else:
        shaft_r = intent.value_of("shaft_opening_diameter") / 2.0
        hole_r = intent.value_of("mounting_hole_diameter") / 2.0
        centre_dist = math.hypot(
            intent.value_of("hole_spacing_x") / 2.0,
            intent.value_of("hole_spacing_y") / 2.0,
        )
        web = centre_dist - hole_r - shaft_r
        ok = web > 0
        checks.append(CheckResult(
            id="pre_hole_overlap",
            stage=CheckStage.PREFLIGHT,
            name="Shaft opening clears mounting holes",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            expected="> 0 mm of material between openings",
            actual=f"{web:.4g} mm",
            measured_value=round(web, 6),
            required_value=0.0,
            conflict_class=None if ok else ConflictClass.CONSTRAINT,
            responsible_parameters=(
                [] if ok else
                ["shaft_opening_diameter", "hole_spacing_x", "mounting_hole_diameter"]
            ),
            message=(
                f"{web:.4g} mm of material separates the shaft opening from each "
                f"mounting hole" if ok else
                "the shaft opening breaks into the mounting holes"
            ),
        ))

    return Report(stage=CheckStage.PREFLIGHT, design_revision=intent.revision, checks=checks)


def hard_constraint_failures(intent: DesignIntent, report: Report) -> list[CheckResult]:
    """Failures that correspond to a HARD constraint.

    Used to explain what the release gate will refuse, without preflight itself
    doing any blocking.
    """
    hard_types = {
        c.type for c in intent.constraints if c.severity is ConstraintSeverity.HARD
    }
    out = []
    for check in report.failures:
        if check.conflict_class in (ConflictClass.SOURCE, ConflictClass.COMPLETENESS):
            out.append(check)
        elif "edge_clearance" in check.id and "min_hole_edge_clearance" in hard_types:
            out.append(check)
        elif check.conflict_class is ConflictClass.CONSTRAINT:
            out.append(check)
    return out
