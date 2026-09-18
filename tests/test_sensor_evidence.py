"""R2 sensor evidence is versioned, traceable and fail-closed."""

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
    SensorTolerance,
)


HASH = "a" * 64


def reference(layer: SensorLayer, *, backend: str | None = None) -> SensorReference:
    return SensorReference(
        layer=layer,
        document_id=f"document.{layer.value}",
        document_sha256=HASH,
        record_ids=(f"record.{layer.value}",),
        backend_id=backend,
        backend_version="1.1.0" if backend else None,
    )


def method() -> SensorMethod:
    return SensorMethod(
        id="method.planar_extent",
        version="1.0.0",
        description="Measure the distance between opposing planar faces.",
    )


def tolerance() -> SensorTolerance:
    return SensorTolerance(
        policy_id="policy.cross_backend",
        policy_version="1.0.0",
        unit="mm",
        absolute=0.01,
        relative=0.0,
    )


def test_governing_numeric_sensor_round_trips_with_traceability():
    evidence = SensorEvidence(
        id="sensor.plate_width.freecad_brep",
        label="FreeCAD measured plate width",
        revision=1,
        design_revision=2,
        quantity="plate_width",
        source=reference(SensorLayer.BREP_MEASUREMENT, backend="freecad"),
        value=45.0,
        unit="mm",
        tolerance=tolerance(),
        method=method(),
        applicability=Applicability.APPLICABLE,
        release_role=SensorReleaseRole.GOVERNING,
        related_record_ids=("dimension.plate_width", "parameter.plate_width"),
    )

    assert SensorEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    assert evidence.schema_version == "1.0.0"
    assert evidence.source.layer is SensorLayer.BREP_MEASUREMENT


def test_visual_findings_are_explicitly_diagnostic():
    evidence = SensorEvidence(
        id="sensor.render.possible_opening",
        label="Possible opening in canonical render",
        revision=1,
        design_revision=2,
        quantity="opening_presence",
        source=reference(SensorLayer.VISUAL_DIAGNOSTIC),
        value=True,
        unit="none",
        method=SensorMethod(
            id="method.render_classifier",
            version="0.1.0",
            description="Advisory classifier over a canonical render.",
        ),
        release_role=SensorReleaseRole.DIAGNOSTIC,
    )

    assert evidence.tolerance is None
    with pytest.raises(ValidationError, match="visual evidence must remain diagnostic"):
        SensorEvidence.model_validate({
            **evidence.model_dump(),
            "release_role": SensorReleaseRole.GOVERNING,
        })


def test_unavailable_sensor_has_no_value_and_cannot_govern():
    evidence = SensorEvidence(
        id="sensor.native_constraint.unavailable",
        label="Native constraint value",
        revision=1,
        design_revision=2,
        quantity="plate_width",
        source=reference(SensorLayer.NATIVE_CONSTRAINT, backend="cadquery"),
        value=None,
        unit="mm",
        method=method(),
        applicability=Applicability.UNSUPPORTED,
        release_role=SensorReleaseRole.DIAGNOSTIC,
        diagnostics=(SensorDiagnostic(
            severity=SensorDiagnosticSeverity.WARNING,
            code="sensor.unsupported",
            message="The backend has no native constraint document.",
        ),),
    )

    assert evidence.value is None
    with pytest.raises(ValidationError, match="unavailable evidence cannot govern"):
        SensorEvidence.model_validate({
            **evidence.model_dump(),
            "release_role": SensorReleaseRole.GOVERNING,
        })
    with pytest.raises(ValidationError, match="must not contain a value"):
        SensorEvidence.model_validate({
            **evidence.model_dump(),
            "value": 45.0,
        })


@pytest.mark.parametrize(
    "layer",
    [
        SensorLayer.ENGINEERING_INTENT_EXPECTATION,
        SensorLayer.FEATURE_IR_VALUE,
    ],
)
def test_planned_layers_cannot_claim_measured_release_authority(layer):
    with pytest.raises(ValidationError, match="cannot govern release"):
        SensorEvidence(
            id=f"sensor.width.{layer.value}",
            label="Planned width",
            revision=1,
            design_revision=2,
            quantity="plate_width",
            source=reference(layer),
            value=45.0,
            unit="mm",
            tolerance=tolerance(),
            method=method(),
            release_role=SensorReleaseRole.GOVERNING,
        )


def test_governing_numeric_evidence_requires_matching_tolerance():
    payload = dict(
        id="sensor.width.brep",
        label="Measured width",
        revision=1,
        design_revision=2,
        quantity="plate_width",
        source=reference(SensorLayer.BREP_MEASUREMENT, backend="freecad"),
        value=45.0,
        unit="mm",
        method=method(),
        release_role=SensorReleaseRole.GOVERNING,
    )
    with pytest.raises(ValidationError, match="requires a tolerance"):
        SensorEvidence(**payload)
    with pytest.raises(ValidationError, match="tolerance unit must match"):
        SensorEvidence(
            **payload,
            tolerance=SensorTolerance(
                policy_id="policy.cross_backend",
                policy_version="1.0.0",
                unit="mm3",
                absolute=0.01,
            ),
        )


def test_reference_revision_and_numeric_values_fail_closed():
    with pytest.raises(ValidationError, match="backend id and version"):
        SensorReference(
            layer=SensorLayer.BREP_MEASUREMENT,
            document_id="document.freecad",
            document_sha256=HASH,
            record_ids=("record.width",),
            backend_id="freecad",
        )
    with pytest.raises(ValidationError):
        SensorReference(
            layer=SensorLayer.BREP_MEASUREMENT,
            document_id="document.bad_hash",
            document_sha256="not-a-hash",
            record_ids=("record.width",),
        )
    with pytest.raises(ValidationError):
        SensorEvidence(
            id="sensor.width.invalid_revision",
            label="Invalid revision",
            revision=0,
            design_revision=2,
            quantity="plate_width",
            source=reference(SensorLayer.BREP_MEASUREMENT, backend="freecad"),
            value=float("nan"),
            unit="mm",
            tolerance=tolerance(),
            method=method(),
            release_role=SensorReleaseRole.GOVERNING,
        )
