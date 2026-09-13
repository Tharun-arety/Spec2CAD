"""Requirement validation: stated constraints re-checked against measured geometry.

Preflight already predicted these symbolically. This stage re-evaluates them on
the finished solid, which is what the release gate acts on. Running both is the
point: a prediction that disagrees with a measurement means one of the two is
wrong, and that is worth surfacing rather than trusting whichever happened to
run last.
"""

from __future__ import annotations

from spec2cad.fusion.conflict_detector import minimum_plate_dimension
from spec2cad.schemas.design_intent import ConstraintSeverity, DesignIntent
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)
from spec2cad.validation import measure as M

# How far a prediction may sit from a measurement before we call it a defect.
PREDICTION_AGREEMENT_TOLERANCE_MM = 1e-3


def run_requirements(shape, intent: DesignIntent) -> Report:
    checks: list[CheckResult] = []

    constraint = intent.constraint("min_hole_edge_clearance")
    if constraint is None:
        checks.append(CheckResult(
            id="req_edge_clearance", stage=CheckStage.REQUIREMENT,
            name="Minimum hole edge clearance", status=CheckStatus.SKIPPED,
            message="no edge-clearance constraint was stated",
        ))
        return Report(
            stage=CheckStage.REQUIREMENT, design_revision=intent.revision, checks=checks
        )

    try:
        mount_r = intent.value_of("mounting_hole_diameter") / 2.0
        measured = M.measured_edge_clearance(shape, mount_r)
    except (ValueError, KeyError) as exc:
        checks.append(CheckResult(
            id="req_edge_clearance", stage=CheckStage.REQUIREMENT,
            name="Minimum hole edge clearance", status=CheckStatus.SKIPPED,
            message=f"could not measure: {exc}",
        ))
        return Report(
            stage=CheckStage.REQUIREMENT, design_revision=intent.revision, checks=checks
        )

    required = constraint.value
    ok = measured >= required - 1e-9
    is_hard = constraint.severity is ConstraintSeverity.HARD

    needed = minimum_plate_dimension(
        intent.value_of("hole_spacing_x"),
        intent.value_of("mounting_hole_diameter"),
        required,
    )

    checks.append(CheckResult(
        id="req_edge_clearance",
        stage=CheckStage.REQUIREMENT,
        name="Minimum hole edge clearance",
        status=CheckStatus.PASS if ok else (
            CheckStatus.FAIL if is_hard else CheckStatus.WARN
        ),
        expected=f">= {required:g} mm",
        actual=f"{measured:.4g} mm",
        required_value=required,
        measured_value=round(measured, 6),
        conflict_class=None if ok else ConflictClass.CONSTRAINT,
        responsible_parameters=(
            [] if ok else ["plate_width", "hole_spacing_x", "mounting_hole_diameter"]
        ),
        message=(
            f"measured {measured:.4g} mm of material between every mounting-hole edge "
            f"and the plate boundary, against a required {required:g} mm"
            if ok else
            f"measured only {measured:.4g} mm between the nearest mounting-hole edge "
            f"and the plate boundary, against a required {required:g} mm. "
            f"The minimum feasible plate width is {needed:g} mm."
        ),
    ))

    return Report(
        stage=CheckStage.REQUIREMENT, design_revision=intent.revision, checks=checks
    )


def compare_prediction_to_measurement(
    preflight: Report, measured: Report
) -> list[CheckResult]:
    """Cross-check preflight predictions against what was actually measured.

    A mismatch is a defect in one of the two stages, not a design problem, so it
    is reported separately from the engineering checks.
    """
    out: list[CheckResult] = []

    pairs = [("pre_edge_clearance_x", "req_edge_clearance")]
    for predicted_id, measured_id in pairs:
        p = preflight.get(predicted_id)
        m = measured.get(measured_id)
        if p is None or m is None:
            continue
        if p.measured_value is None or m.measured_value is None:
            continue
        delta = abs(p.measured_value - m.measured_value)
        agree = delta <= PREDICTION_AGREEMENT_TOLERANCE_MM
        out.append(CheckResult(
            id=f"xcheck_{measured_id}",
            stage=CheckStage.REQUIREMENT,
            name="Preflight prediction matches measurement",
            status=CheckStatus.PASS if agree else CheckStatus.FAIL,
            expected=f"predicted {p.measured_value:.6g} mm",
            actual=f"measured {m.measured_value:.6g} mm",
            required_value=p.measured_value,
            measured_value=m.measured_value,
            tolerance=PREDICTION_AGREEMENT_TOLERANCE_MM,
            conflict_class=None if agree else ConflictClass.EXECUTION,
            message=(
                "the symbolic prediction agrees with the measured geometry"
                if agree else
                f"preflight predicted {p.measured_value:.6g} mm but the solid measures "
                f"{m.measured_value:.6g} mm (difference {delta:.6g} mm). One of the two "
                f"stages is wrong; this is a defect in the pipeline, not in the design."
            ),
        ))
    return out
