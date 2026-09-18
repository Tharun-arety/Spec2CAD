"""R2 governing sensor consistency participates in the measured release gate."""

from pathlib import Path

import pytest

from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    GoverningConsistencyStatus,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
    assess_governing_consistency,
    build_consistency_matrices,
)
from spec2cad.validation.gate import ReleaseStatus, evaluate_release


MOTOR = Path(__file__).resolve().parents[1] / "examples" / "motor_adapter"
HASH = "a" * 64


@pytest.fixture
def motor_inputs():
    initial = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    revision = repair(
        initial, "widen_to_recommended", approved_by="r2-gate-test"
    ).latest
    return revision.intent, revision.measured


def sensor(
    sensor_id,
    layer,
    value,
    role,
    *,
    tolerance=True,
):
    backend = "freecad" if layer is SensorLayer.BREP_MEASUREMENT else None
    return SensorEvidence(
        id=sensor_id,
        label=sensor_id,
        revision=1,
        design_revision=2,
        quantity="plate_width",
        source=SensorReference(
            layer=layer,
            document_id=f"document.{sensor_id}",
            document_sha256=HASH,
            record_ids=(f"record.{sensor_id}",),
            backend_id=backend,
            backend_version="1.0.0" if backend else None,
        ),
        value=value,
        unit="mm",
        tolerance=(
            SensorTolerance(
                policy_id="policy.test", policy_version="1.0.0",
                unit="mm", absolute=0.01,
            )
            if tolerance else None
        ),
        method=SensorMethod(
            id="method.test", version="1.0.0", description="Gate test sensor.",
        ),
        release_role=role,
    )


def assessment(evidence):
    return assess_governing_consistency(
        evidence, build_consistency_matrices(evidence)
    )


def test_governing_inconsistency_blocks_step_release(motor_inputs):
    evidence = (
        sensor(
            "sensor.reference", SensorLayer.FEATURE_IR_VALUE, 40.0,
            SensorReleaseRole.REFERENCE,
        ),
        sensor(
            "sensor.governing", SensorLayer.BREP_MEASUREMENT, 41.0,
            SensorReleaseRole.GOVERNING,
        ),
    )
    result = assessment(evidence)

    decision = evaluate_release(
        *motor_inputs, governing_consistency=result
    )

    assert result.status is GoverningConsistencyStatus.INCONSISTENT
    assert decision.status is ReleaseStatus.BLOCKED
    assert not decision.step_export_allowed
    assert decision.blocking[-1].id == "gate_sensor_consistency"
    assert decision.blocking[-1].actual == "inconsistent"


def test_unassessed_governing_comparison_blocks_instead_of_false_success(
    motor_inputs,
):
    evidence = (
        sensor(
            "sensor.reference", SensorLayer.FEATURE_IR_VALUE, 40.0,
            SensorReleaseRole.REFERENCE, tolerance=False,
        ),
        sensor(
            "sensor.governing", SensorLayer.BREP_MEASUREMENT, 40.0,
            SensorReleaseRole.GOVERNING,
        ),
    )
    result = assessment(evidence)
    decision = evaluate_release(
        *motor_inputs, governing_consistency=result
    )

    assert result.status is GoverningConsistencyStatus.NOT_ASSESSED
    assert decision.status is ReleaseStatus.BLOCKED


def test_consistent_governing_pair_allows_existing_measured_gate(motor_inputs):
    evidence = (
        sensor(
            "sensor.reference", SensorLayer.FEATURE_IR_VALUE, 40.0,
            SensorReleaseRole.REFERENCE,
        ),
        sensor(
            "sensor.governing", SensorLayer.BREP_MEASUREMENT, 40.0,
            SensorReleaseRole.GOVERNING,
        ),
    )
    result = assessment(evidence)
    decision = evaluate_release(
        *motor_inputs, governing_consistency=result
    )

    assert result.status is GoverningConsistencyStatus.CONSISTENT
    assert decision.status is ReleaseStatus.AUTHORISED


def test_consistent_assessment_from_another_revision_fails_closed(motor_inputs):
    evidence = (
        sensor(
            "sensor.reference", SensorLayer.FEATURE_IR_VALUE, 40.0,
            SensorReleaseRole.REFERENCE,
        ),
        sensor(
            "sensor.governing", SensorLayer.BREP_MEASUREMENT, 40.0,
            SensorReleaseRole.GOVERNING,
        ),
    )
    stale = assessment(evidence).model_copy(update={"design_revision": 99})

    decision = evaluate_release(
        *motor_inputs, governing_consistency=stale
    )

    assert decision.status is ReleaseStatus.BLOCKED
    assert decision.blocking[-1].id == "gate_sensor_consistency"
    assert decision.blocking[-1].actual == "revision_mismatch"


def test_visual_and_diagnostic_disagreement_cannot_block(motor_inputs):
    reference = sensor(
        "sensor.reference", SensorLayer.FEATURE_IR_VALUE, 40.0,
        SensorReleaseRole.REFERENCE,
    )
    governing = sensor(
        "sensor.governing", SensorLayer.BREP_MEASUREMENT, 40.0,
        SensorReleaseRole.GOVERNING,
    )
    visual = sensor(
        "sensor.visual", SensorLayer.VISUAL_DIAGNOSTIC, 99.0,
        SensorReleaseRole.DIAGNOSTIC,
    )
    result = assessment((reference, governing, visual))
    decision = evaluate_release(
        *motor_inputs, governing_consistency=result
    )

    assert result.status is GoverningConsistencyStatus.CONSISTENT
    assert decision.status is ReleaseStatus.AUTHORISED

    diagnostic_only = assessment((visual, visual.model_copy(update={
        "id": "sensor.visual.other", "value": 1.0,
    })))
    assert not diagnostic_only.governing
    assert evaluate_release(
        *motor_inputs, governing_consistency=diagnostic_only
    ).status is ReleaseStatus.AUTHORISED
