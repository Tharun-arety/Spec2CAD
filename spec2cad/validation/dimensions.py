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


def _missing(intent: DesignIntent, *names: str) -> list[str]:
    """Which of these parameters the intent does not carry a value for.

    A text-only prompt need not describe every feature the motor-adapter slice
    happens to have. The compiler already omits the operations it cannot
    resolve, so a check for an absent feature has nothing to measure -- it is
    skipped and says which parameter is missing, the way preflight does. It is
    not a failure: failing here would report a hole as built wrong when the
    design never asked for one.
    """
    return [n for n in names if not intent.has(n)]


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

    if intent.has("outer_diameter") and intent.has("body_length"):
        cylindrical = M.cylindrical_extents(shape)
        checks.append(_compare(
            "dim_outer_diameter", "Outer diameter", cylindrical.outer_diameter,
            intent.value_of("outer_diameter"), responsible=["outer_diameter"],
            tol=1e-3,
        ))
        checks.append(_compare(
            "dim_body_length", "Body length", cylindrical.axial_length,
            intent.value_of("body_length"), responsible=["body_length"],
            tol=1e-3,
        ))
        if intent.has("inner_diameter"):
            intended_inner = intent.value_of("inner_diameter")
            if cylindrical.inner_diameter is not None:
                checks.append(_compare(
                    "dim_inner_diameter", "Inner diameter", cylindrical.inner_diameter,
                    intended_inner, responsible=["inner_diameter"], tol=1e-3,
                ))
            else:
                checks.append(CheckResult(
                    id="dim_inner_diameter", stage=CheckStage.DIMENSIONAL,
                    name="Inner diameter", status=CheckStatus.FAIL,
                    expected=f"{intended_inner:g} mm", actual="not found",
                    conflict_class=ConflictClass.EXECUTION,
                    responsible_parameters=["inner_diameter"],
                    message="no axial bore of the intended diameter was found",
                ))
        return Report(
            stage=CheckStage.DIMENSIONAL,
            design_revision=intent.revision,
            checks=checks,
        )

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

    absent = _missing(intent, "mounting_hole_diameter", "mounting_hole_count")
    if absent:
        checks.append(CheckResult(
            id="dim_hole_count", stage=CheckStage.DIMENSIONAL,
            name="Mounting hole count", status=CheckStatus.SKIPPED,
            responsible_parameters=absent,
            message=f"cannot evaluate: missing {', '.join(absent)}",
        ))
    else:
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
            if len(mounts) >= 2 and not _missing(intent, "hole_spacing_x", "hole_spacing_y"):
                sx, sy = M.hole_spacing(mounts)
                checks.append(_compare("dim_hole_spacing_x", "Hole spacing (x)",
                                       sx, intent.value_of("hole_spacing_x"),
                                       responsible=["hole_spacing_x"]))
                checks.append(_compare("dim_hole_spacing_y", "Hole spacing (y)",
                                       sy, intent.value_of("hole_spacing_y"),
                                       responsible=["hole_spacing_y"]))

    if not intent.has("shaft_opening_diameter"):
        checks.append(CheckResult(
            id="dim_shaft_opening", stage=CheckStage.DIMENSIONAL,
            name="Shaft opening diameter", status=CheckStatus.SKIPPED,
            responsible_parameters=["shaft_opening_diameter"],
            message="cannot evaluate: missing shaft_opening_diameter",
        ))
    else:
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

    slot_names = ("slot_width", "slot_length", "slot_count")
    if any(intent.has(name) for name in slot_names):
        absent_slots = _missing(intent, *slot_names)
        if absent_slots:
            checks.append(CheckResult(
                id="dim_slot_count", stage=CheckStage.DIMENSIONAL,
                name="Slot pattern", status=CheckStatus.SKIPPED,
                responsible_parameters=absent_slots,
                message=f"cannot evaluate: missing {', '.join(absent_slots)}",
            ))
        else:
            measured_slots = M.slot_features(M.top_face(shape))
            intended_count = int(intent.value_of("slot_count"))
            count_ok = len(measured_slots) == intended_count
            checks.append(CheckResult(
                id="dim_slot_count", stage=CheckStage.DIMENSIONAL,
                name="Slot count",
                status=CheckStatus.PASS if count_ok else CheckStatus.FAIL,
                expected=str(intended_count), actual=str(len(measured_slots)),
                required_value=float(intended_count),
                measured_value=float(len(measured_slots)),
                conflict_class=None if count_ok else ConflictClass.EXECUTION,
                responsible_parameters=[] if count_ok else ["slot_count"],
                message=f"{len(measured_slots)} obround slots were measured on the solid",
            ))
            if measured_slots:
                checks.append(_compare(
                    "dim_slot_width", "Slot width", measured_slots[0].width,
                    intent.value_of("slot_width"), responsible=["slot_width"],
                ))
                checks.append(_compare(
                    "dim_slot_length", "Slot length", measured_slots[0].length,
                    intent.value_of("slot_length"), responsible=["slot_length"],
                ))
                if len(measured_slots) >= 2 and intent.has("slot_spacing_x"):
                    xs = [slot.x for slot in measured_slots]
                    spacing = max(xs) - min(xs)
                    checks.append(_compare(
                        "dim_slot_spacing_x", "Slot spacing (x)", spacing,
                        intent.value_of("slot_spacing_x"),
                        responsible=["slot_spacing_x"],
                    ))

    if intent.has("external_fillet"):
        radius = intent.value_of("external_fillet")
        count = M.external_corner_fillet_count(shape, radius)
        ok = count == 4
        checks.append(CheckResult(
            id="dim_external_fillet", stage=CheckStage.DIMENSIONAL,
            name="External corner fillets",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            expected="4", actual=str(count),
            required_value=4.0, measured_value=float(count),
            conflict_class=None if ok else ConflictClass.EXECUTION,
            responsible_parameters=[] if ok else ["external_fillet"],
            message=f"measured {count} external quarter-circle arcs of radius {radius:g} mm",
        ))

    return Report(
        stage=CheckStage.DIMENSIONAL, design_revision=intent.revision, checks=checks
    )
