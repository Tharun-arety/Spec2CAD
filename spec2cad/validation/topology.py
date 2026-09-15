"""Topological validation, measured on the finished solid."""

from __future__ import annotations

import math

from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)
from spec2cad.validation import measure as M


def _absent_is_zero(intent: DesignIntent, name: str) -> float:
    """This feature's parameter, or 0.0 when the design does not have it.

    expected_volume() only ever subtracts a feature's volume, so a feature the
    compiler did not build subtracts nothing. Reading these unconditionally
    raised TypeError on any design without the full motor-adapter feature set,
    which the surrounding handler turned into a SKIPPED check -- so the volume
    comparison, the one check that actually catches a feature built at the
    wrong size, quietly stopped running for every text-only prompt while the
    release still reported "authorised".

    Only for features whose presence is decided by this one parameter. The
    mounting pattern is not one of them; it is resolved at the call site.
    """
    return intent.value_of(name) if intent.has(name) else 0.0


def run_topology(shape, intent: DesignIntent, *, skip_analytic_volume: bool = False) -> Report:
    checks: list[CheckResult] = []

    valid = bool(shape.isValid())
    checks.append(CheckResult(
        id="top_valid_solid", stage=CheckStage.TOPOLOGY, name="Valid solid",
        status=CheckStatus.PASS if valid else CheckStatus.FAIL,
        expected="yes", actual="yes" if valid else "no",
        conflict_class=None if valid else ConflictClass.EXECUTION,
        message="the kernel reports a topologically valid shape" if valid
                else "the kernel reports an invalid shape",
    ))

    n_solids = len(shape.Solids())
    checks.append(CheckResult(
        id="top_body_count", stage=CheckStage.TOPOLOGY, name="Body count",
        status=CheckStatus.PASS if n_solids == 1 else CheckStatus.FAIL,
        expected="1", actual=str(n_solids),
        conflict_class=None if n_solids == 1 else ConflictClass.EXECUTION,
        message="a single connected body" if n_solids == 1
                else f"{n_solids} bodies: the part is not one piece",
    ))

    volume = float(shape.Volume())
    checks.append(CheckResult(
        id="top_positive_volume", stage=CheckStage.TOPOLOGY, name="Positive volume",
        status=CheckStatus.PASS if volume > 0 else CheckStatus.FAIL,
        expected="> 0 mm3", actual=f"{volume:.4f} mm3", measured_value=volume,
        conflict_class=None if volume > 0 else ConflictClass.EXECUTION,
        message="the solid encloses material",
    ))

    try:
        through, features = M.through_holes(shape)
        checks.append(CheckResult(
            id="top_through_holes", stage=CheckStage.TOPOLOGY,
            name="All openings pass through",
            status=CheckStatus.PASS if through else CheckStatus.FAIL,
            expected="every opening present on both faces",
            actual=f"{len(features)} openings, matching" if through
                   else "top and bottom openings differ",
            conflict_class=None if through else ConflictClass.EXECUTION,
            message="each opening appears identically on the top and bottom faces"
                    if through else
                    "at least one cut did not pass through the plate",
        ))
    except ValueError as exc:
        checks.append(CheckResult(
            id="top_through_holes", stage=CheckStage.TOPOLOGY,
            name="All openings pass through", status=CheckStatus.SKIPPED,
            message=f"could not measure: {exc}",
        ))

    if skip_analytic_volume:
        return Report(stage=CheckStage.TOPOLOGY, design_revision=intent.revision, checks=checks)

    # Material integrity: compare against the analytically expected volume.
    # This replaces face-type counting -- it is tolerance-aware and actually
    # catches a feature built at the wrong size.
    try:
        if intent.has("outer_diameter") and intent.has("body_length"):
            outer = intent.value_of("outer_diameter")
            inner = (
                intent.value_of("inner_diameter")
                if intent.has("inner_diameter") else 0.0
            )
            expected = math.pi * (outer * outer - inner * inner) * 0.25 * intent.value_of(
                "body_length"
            )
            delta = abs(volume - expected)
            ok = delta <= M.VOLUME_TOLERANCE_MM3
            checks.append(CheckResult(
                id="top_material_integrity", stage=CheckStage.TOPOLOGY,
                name="Volume matches analytic model",
                status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                expected=f"{expected:.6f} mm3", actual=f"{volume:.6f} mm3",
                required_value=expected, measured_value=volume,
                tolerance=M.VOLUME_TOLERANCE_MM3,
                conflict_class=None if ok else ConflictClass.EXECUTION,
                message=(
                    f"measured cylindrical volume agrees to {delta:.2e} mm3"
                    if ok else
                    f"measured cylindrical volume differs by {delta:.6f} mm3"
                ),
            ))
            return Report(
                stage=CheckStage.TOPOLOGY,
                design_revision=intent.revision,
                checks=checks,
            )

        extents = M.plate_extents(shape)

        # Mirror what compile_design() actually emits, or this check measures a
        # part the compiler never built: the pattern needs both a spacing and a
        # diameter to be emitted at all, and it falls back to four holes when
        # the count is unstated. Keep in step with cad/compiler.py.
        if intent.has("hole_spacing_x") and intent.has("mounting_hole_diameter"):
            hole_diameter = intent.value_of("mounting_hole_diameter")
            hole_count = (
                int(intent.value_of("mounting_hole_count"))
                if intent.has("mounting_hole_count") else 4
            )
        else:
            hole_diameter, hole_count = 0.0, 0

        expected = M.expected_volume(
            width=extents.width,
            height=extents.height,
            thickness=extents.thickness,
            shaft_diameter=_absent_is_zero(intent, "shaft_opening_diameter"),
            hole_diameter=hole_diameter,
            hole_count=hole_count,
            chamfer=_absent_is_zero(intent, "external_chamfer"),
            slot_width=_absent_is_zero(intent, "slot_width"),
            slot_length=_absent_is_zero(intent, "slot_length"),
            slot_count=(
                int(intent.value_of("slot_count")) if intent.has("slot_count") else 0
            ),
            fillet=_absent_is_zero(intent, "external_fillet"),
        )
        delta = abs(volume - expected)
        ok = delta <= M.VOLUME_TOLERANCE_MM3
        checks.append(CheckResult(
            id="top_material_integrity", stage=CheckStage.TOPOLOGY,
            name="Volume matches analytic model",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            expected=f"{expected:.6f} mm3", actual=f"{volume:.6f} mm3",
            required_value=expected, measured_value=volume,
            tolerance=M.VOLUME_TOLERANCE_MM3,
            conflict_class=None if ok else ConflictClass.EXECUTION,
            message=(
                f"measured volume agrees with the analytic model to {delta:.2e} mm3"
                if ok else
                f"measured volume differs from the analytic model by {delta:.6f} mm3: "
                f"a feature was built at the wrong size or an operation was lost"
            ),
        ))
    except (KeyError, ValueError, TypeError) as exc:
        checks.append(CheckResult(
            id="top_material_integrity", stage=CheckStage.TOPOLOGY,
            name="Volume matches analytic model", status=CheckStatus.SKIPPED,
            message=f"could not compute expected volume: {exc}",
        ))

    return Report(stage=CheckStage.TOPOLOGY, design_revision=intent.revision, checks=checks)
