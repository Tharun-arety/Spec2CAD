"""Topological validation, measured on the finished solid."""

from __future__ import annotations

from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)
from spec2cad.validation import measure as M


def run_topology(shape, intent: DesignIntent) -> Report:
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

    # Material integrity: compare against the analytically expected volume.
    # This replaces face-type counting -- it is tolerance-aware and actually
    # catches a feature built at the wrong size.
    try:
        extents = M.plate_extents(shape)
        expected = M.expected_volume(
            width=extents.width,
            height=extents.height,
            thickness=extents.thickness,
            shaft_diameter=intent.value_of("shaft_opening_diameter"),
            hole_diameter=intent.value_of("mounting_hole_diameter"),
            hole_count=int(intent.value_of("mounting_hole_count")),
            chamfer=intent.value_of("external_chamfer"),
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
