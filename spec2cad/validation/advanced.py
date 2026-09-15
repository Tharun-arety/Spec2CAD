"""Generic operation-level validation for profile and sheet-metal geometry."""

from spec2cad.cad.executor import ExecutionResult
from spec2cad.schemas.report import (
    CheckResult, CheckStage, CheckStatus, ConflictClass, Report,
)


def run_advanced_geometry(execution: ExecutionResult, revision: int) -> Report:
    checks: list[CheckResult] = []
    for measurement in execution.measurements:
        valid = measurement.is_valid and measurement.solid_count == 1
        changed = not measurement.no_op
        checks.append(CheckResult(
            id=f"advanced_{measurement.operation_id}_valid",
            stage=CheckStage.DIMENSIONAL,
            name=f"{measurement.operation_id} produced valid geometry",
            status=CheckStatus.PASS if valid else CheckStatus.FAIL,
            expected="one valid solid", actual=(
                f"{measurement.solid_count} solid(s), valid={measurement.is_valid}"
            ),
            conflict_class=None if valid else ConflictClass.EXECUTION,
            message="operation produced one valid solid" if valid else "operation geometry is invalid",
        ))
        checks.append(CheckResult(
            id=f"advanced_{measurement.operation_id}_material_change",
            stage=CheckStage.DIMENSIONAL,
            name=f"{measurement.operation_id} changed material",
            status=CheckStatus.PASS if changed else CheckStatus.FAIL,
            expected="non-zero volume delta",
            actual=f"{measurement.volume_delta:.6g} mm3",
            measured_value=measurement.volume_delta,
            conflict_class=None if changed else ConflictClass.EXECUTION,
            message="B-Rep volume changed" if changed else "operation was a no-op",
        ))
        expected = execution.context.derived.get(
            f"{measurement.operation_id}.expected_volume"
        )
        if expected is not None:
            delta = abs(measurement.volume - expected)
            ok = delta <= 1e-3
            checks.append(CheckResult(
                id=f"advanced_{measurement.operation_id}_analytic_volume",
                stage=CheckStage.DIMENSIONAL,
                name=f"{measurement.operation_id} matches analytic volume",
                status=CheckStatus.PASS if ok else CheckStatus.FAIL,
                expected=f"{expected:.6f} mm3",
                actual=f"{measurement.volume:.6f} mm3",
                required_value=expected,
                measured_value=measurement.volume,
                tolerance=1e-3,
                conflict_class=None if ok else ConflictClass.EXECUTION,
                message=(
                    f"B-Rep agrees with independent bend-area calculation to {delta:.3g} mm3"
                    if ok else f"B-Rep differs from bend-area calculation by {delta:.6g} mm3"
                ),
            ))
    return Report(stage=CheckStage.DIMENSIONAL, design_revision=revision, checks=checks)
