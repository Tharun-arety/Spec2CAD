"""Visual diagnostics cannot enter the release authority path."""

import inspect

import pytest
from pydantic import ValidationError

from spec2cad.reconciliation import (
    Applicability,
    SensorDiagnostic,
    SensorDiagnosticSeverity,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    visual_diagnostic_evidence,
)
from spec2cad.validation.gate import evaluate_release


HASH = "a" * 64


def visual_payload(applicability=Applicability.APPLICABLE):
    unavailable = applicability is not Applicability.APPLICABLE
    return dict(
        id="sensor.visual.guardrail",
        label="Visual guardrail",
        revision=1,
        design_revision=2,
        quantity="visual_health",
        source=SensorReference(
            layer=SensorLayer.VISUAL_DIAGNOSTIC,
            document_id="artifact.canonical_view",
            document_sha256=HASH,
            record_ids=("view.motor.isometric",),
        ),
        value=None if unavailable else True,
        unit="none",
        method=SensorMethod(
            id="method.visual_guardrail",
            version="0.1.0",
            description="Unpromoted advisory visual method.",
        ),
        applicability=applicability,
        diagnostics=(
            (SensorDiagnostic(
                severity=SensorDiagnosticSeverity.WARNING,
                code="sensor.not_assessed",
                message="Visual method unavailable.",
            ),)
            if unavailable
            else ()
        ),
    )


@pytest.mark.parametrize(
    "applicability",
    [Applicability.APPLICABLE, Applicability.NOT_ASSESSED, Applicability.UNSUPPORTED],
)
@pytest.mark.parametrize(
    "role",
    [SensorReleaseRole.GOVERNING, SensorReleaseRole.REFERENCE],
)
def test_visual_evidence_rejects_every_non_diagnostic_role(applicability, role):
    with pytest.raises(ValidationError, match="visual evidence must remain diagnostic"):
        SensorEvidence(**visual_payload(applicability), release_role=role)


def test_visual_factory_can_only_emit_diagnostic_evidence():
    finding = visual_diagnostic_evidence(
        id="sensor.visual.factory_guardrail",
        label="Visual factory guardrail",
        revision=1,
        design_revision=2,
        quantity="visual_health",
        document_id="artifact.canonical_view",
        document_sha256=HASH,
        record_ids=("view.motor.isometric",),
        method_id="method.visual_guardrail",
        method_version="0.1.0",
        method_description="Unpromoted advisory visual method.",
        value=True,
    )
    assert finding.release_role is SensorReleaseRole.DIAGNOSTIC


def test_release_gate_has_no_render_or_visual_evidence_input():
    parameters = inspect.signature(evaluate_release).parameters
    assert tuple(parameters) == (
        "intent",
        "measured_reports",
        "governing_reconciliation",
        "governing_consistency",
    )
    source = inspect.getsource(inspect.getmodule(evaluate_release))
    assert "SensorEvidence" not in source
    assert "canonical_views" not in source
