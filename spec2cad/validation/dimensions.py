"""Dimensional validation: measured geometry vs intended parameters.

Every value on the left of these comparisons is read off the solid. None of
them is echoed from the input parameters, which would make the check vacuous --
a dimensional report that merely restates its inputs passes even when the
executor built the wrong thing.
"""

from __future__ import annotations

from typing import Optional

from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)
from spec2cad.validation import measure as M

TOL = M.LINEAR_TOLERANCE_MM


def _compare(
    check_id: str,
    name: str,
    measured: float,
    intended: float,
    unit: str = "mm",
    tol: float = TOL,
    responsible: Optional[list[str]] = None,
) -> CheckResult:
    ok = abs(measured - intended) <= tol
    return CheckResult(
        id=check_id, stage=CheckStage.DIMENSIONAL, name=name,
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        expected=f"{intended:g} {unit}", actual=f"{measured:.6g} {unit}",
        required_value=intended, measured_value=measured, tolerance=tol,
        conflict_class=None if ok else ConflictClass.EXECUTION,
        responsible_parameters=[] if ok else (responsible or []),
        message=(
            f"measured {measured:.6g} {unit} against an intended {intended:g} {unit}"
            if ok else
            f"measured {measured:.6g} {unit} but {intended:g} {unit} was intended "
            f"(difference {abs(measured - intended):.6g} {unit})"
        ),
    )


def run_dimensions(shape, intent: DesignIntent) -> Report:
    checks: list[CheckResult] = []

    try:
        extents = M.plate_extents(shape)
    except ValueError as exc:
        return Report(
            stage=CheckStage.DIMENSIONAL, design_revision=intent.revision,
            checks=[CheckResult(
                id="dim_extents", stage=CheckStage.DIMENSIONAL, name="Plate extents",
                status=CheckStatus.SKIPPED, message=f"could not measure: {exc}",
            )],
        )

    checks.append(_compare("dim_plate_width", "Plate width",
                           extents.width, intent.value_of("plate_width"),
                           responsible=["plate_width"]))
    checks.append(_compare("dim_plate_height", "Plate height",
                           extents.height, intent.value_of("plate_height"),
                           responsible=["plate_height"]))
    checks.append(_compare("dim_plate_thickness", "Plate thickness",
                           extents.thickness, intent.value_of("plate_thickness"),
                           responsible=["plate_thickness"]))

    features = M.circular_features(M.top_face(shape))
    mount_r = intent.value_of("mounting_hole_diameter") / 2.0
    mounts = M.features_near_radius(features, mount_r)

    intended_count = int(intent.value_of("mounting_hole_count"))
    ok = len(mounts) == intended_count
    checks.append(CheckResult(
        id="dim_hole_count", stage=CheckStage.DIMENSIONAL, name="Mounting hole count",
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        expected=str(intended_count), actual=str(len(mounts)),
        required_value=float(intended_count), measured_value=float(len(mounts)),
        conflict_class=None if ok else ConflictClass.EXECUTION,
        responsible_parameters=[] if ok else ["mounting_hole_count"],
        message=f"{len(mounts)} mounting holes of the intended diameter were found",
    ))

    if mounts:
        checks.append(_compare(
            "dim_hole_diameter", "Mounting hole diameter",
            mounts[0].diameter, intent.value_of("mounting_hole_diameter"),
            responsible=["mounting_hole_diameter"],
        ))
        if len(mounts) >= 2:
            sx, sy = M.hole_spacing(mounts)
            checks.append(_compare("dim_hole_spacing_x", "Hole spacing (x)",
                                   sx, intent.value_of("hole_spacing_x"),
                                   responsible=["hole_spacing_x"]))
            checks.append(_compare("dim_hole_spacing_y", "Hole spacing (y)",
                                   sy, intent.value_of("hole_spacing_y"),
                                   responsible=["hole_spacing_y"]))

    shaft_r = intent.value_of("shaft_opening_diameter") / 2.0
    shafts = M.features_near_radius(features, shaft_r)
    if shafts:
        checks.append(_compare(
            "dim_shaft_opening", "Shaft opening diameter",
            shafts[0].diameter, intent.value_of("shaft_opening_diameter"),
            responsible=["shaft_opening_diameter"],
        ))
    else:
        checks.append(CheckResult(
            id="dim_shaft_opening", stage=CheckStage.DIMENSIONAL,
            name="Shaft opening diameter", status=CheckStatus.FAIL,
            expected=f"{intent.value_of('shaft_opening_diameter'):g} mm",
            actual="not found",
            conflict_class=ConflictClass.EXECUTION,
            responsible_parameters=["shaft_opening_diameter"],
            message="no opening of the intended shaft diameter was found in the solid",
        ))

    return Report(
        stage=CheckStage.DIMENSIONAL, design_revision=intent.revision, checks=checks
    )
