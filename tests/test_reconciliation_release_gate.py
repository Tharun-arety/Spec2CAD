"""Classified cross-backend evidence participates in the measured release gate."""

from pathlib import Path

import pytest

from spec2cad.reconciliation import (
    ClassifiedReconciliation,
    ReconciliationClassification,
)
from spec2cad.validation.gate import ReleaseStatus, evaluate_release
from spec2cad.pipeline import repair, run


MOTOR = Path(__file__).resolve().parents[1] / "examples" / "motor_adapter"


@pytest.fixture
def motor_inputs():
    v1 = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    revision = repair(
        v1, "widen_to_recommended", approved_by="gate-test"
    ).latest
    return revision.intent, revision.measured


def _classification(value, *, governing=True):
    return ClassifiedReconciliation(
        feature_ir_sha256="a" * 64,
        classification=value,
        governing=governing,
        reasons=(f"test {value.value}",),
    )


@pytest.mark.parametrize(
    "classification",
    [
        ReconciliationClassification.PIPELINE_DEFECT,
        ReconciliationClassification.BACKEND_DIVERGENCE,
        ReconciliationClassification.SENSOR_DISAGREEMENT,
        ReconciliationClassification.UNSUPPORTED,
        ReconciliationClassification.NOT_ASSESSED,
    ],
)
def test_every_non_consistent_governing_classification_blocks(
    classification, motor_inputs
):
    intent, reports = motor_inputs
    decision = evaluate_release(
        intent,
        reports,
        governing_reconciliation=_classification(classification),
    )
    assert decision.status is ReleaseStatus.BLOCKED
    assert decision.step_export_allowed is False
    assert decision.blocking[-1].id == "gate_cross_backend_reconciliation"
    assert decision.blocking[-1].actual == classification.value


def test_consistent_reconciliation_allows_existing_measured_gate_to_authorise(
    motor_inputs,
):
    intent, reports = motor_inputs
    decision = evaluate_release(
        intent,
        reports,
        governing_reconciliation=_classification(
            ReconciliationClassification.CONSISTENT
        ),
    )
    assert decision.status is ReleaseStatus.AUTHORISED
    assert decision.step_export_allowed


def test_non_governing_classification_remains_advisory(motor_inputs):
    intent, reports = motor_inputs
    decision = evaluate_release(
        intent,
        reports,
        governing_reconciliation=_classification(
            ReconciliationClassification.BACKEND_DIVERGENCE,
            governing=False,
        ),
    )
    assert decision.status is ReleaseStatus.AUTHORISED
