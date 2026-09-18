"""R2 quantity matrices compare sensors without making release decisions."""

import pytest

from spec2cad.reconciliation import (
    Applicability,
    ConsistencyStatus,
    SensorDiagnostic,
    SensorDiagnosticSeverity,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
    GovernedQuantity,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    ObservationSource,
    ObservationUnit,
    build_consistency_matrices,
    sensor_evidence_from_observation_set,
)


HASH = "a" * 64


def sensor(
    sensor_id: str,
    value,
    *,
    quantity: str = "plate_width",
    unit: str = "mm",
    design_revision: int = 2,
    tolerance: bool = True,
    applicability: Applicability = Applicability.APPLICABLE,
) -> SensorEvidence:
    unavailable = applicability is not Applicability.APPLICABLE
    return SensorEvidence(
        id=sensor_id,
        label=sensor_id,
        revision=1,
        design_revision=design_revision,
        quantity=quantity,
        source=SensorReference(
            layer=SensorLayer.ENGINEERING_INTENT_EXPECTATION,
            document_id=f"document.{sensor_id}",
            document_sha256=HASH,
            record_ids=(f"record.{sensor_id}",),
        ),
        value=None if unavailable else value,
        unit=unit,
        tolerance=(
            SensorTolerance(
                policy_id="policy.test",
                policy_version="1.0.0",
                unit=unit,
                absolute=0.01,
            )
            if tolerance
            else None
        ),
        method=SensorMethod(
            id="method.test",
            version="1.0.0",
            description="Test sensor.",
        ),
        applicability=applicability,
        release_role=SensorReleaseRole.REFERENCE,
        diagnostics=(
            (SensorDiagnostic(
                severity=SensorDiagnosticSeverity.WARNING,
                code="sensor.not_assessed",
                message="Test sensor unavailable.",
            ),)
            if unavailable
            else ()
        ),
    )


def test_numeric_matrix_is_deterministic_complete_and_symmetric():
    evidence = (
        sensor("sensor.width.brep", 45.005),
        sensor("sensor.width.eig", 45.0),
        sensor("sensor.width.feature", 45.0),
    )
    matrix = build_consistency_matrices(tuple(reversed(evidence)))[0]

    assert matrix.sensor_ids == tuple(sorted(item.id for item in evidence))
    assert len(matrix.cells) == 9
    assert matrix.cell("sensor.width.eig", "sensor.width.brep").status is (
        ConsistencyStatus.CONSISTENT
    )
    assert matrix.cell("sensor.width.brep", "sensor.width.eig").status is (
        ConsistencyStatus.CONSISTENT
    )
    assert matrix.cell("sensor.width.eig", "sensor.width.brep").maximum_error == (
        matrix.cell("sensor.width.brep", "sensor.width.eig").maximum_error
    )
    assert type(matrix).model_validate_json(matrix.model_dump_json()) == matrix


def test_numeric_and_vector_disagreements_are_visible():
    numeric = build_consistency_matrices((
        sensor("sensor.width.expected", 45.0),
        sensor("sensor.width.measured", 45.02),
    ))[0]
    vectors = build_consistency_matrices((
        sensor("sensor.centers.left", (0.0, 0.0, 10.0, 0.0), quantity="centers"),
        sensor("sensor.centers.right", (0.0, 0.0, 10.02, 0.0), quantity="centers"),
    ))[0]

    assert numeric.cell(*numeric.sensor_ids).status is ConsistencyStatus.INCONSISTENT
    assert numeric.cell(*numeric.sensor_ids).maximum_error == pytest.approx(0.02)
    assert vectors.cell(*vectors.sensor_ids).status is ConsistencyStatus.INCONSISTENT
    assert vectors.cell(*vectors.sensor_ids).maximum_error == pytest.approx(0.02)


def test_unavailable_or_incompatible_pairs_are_not_assessed():
    evidence = (
        sensor("sensor.width.available", 45.0),
        sensor(
            "sensor.width.unavailable",
            None,
            applicability=Applicability.NOT_ASSESSED,
        ),
        sensor("sensor.width.other_unit", 45.0, unit="mm3"),
        sensor("sensor.width.no_tolerance", 45.0, tolerance=False),
    )
    matrix = build_consistency_matrices(evidence)[0]

    assert matrix.cell(
        "sensor.width.available", "sensor.width.unavailable"
    ).status is ConsistencyStatus.NOT_ASSESSED
    assert matrix.cell(
        "sensor.width.available", "sensor.width.other_unit"
    ).status is ConsistencyStatus.NOT_ASSESSED
    assert matrix.cell(
        "sensor.width.available", "sensor.width.no_tolerance"
    ).status is ConsistencyStatus.NOT_ASSESSED


def test_categorical_pairs_compare_exactly_without_tolerance():
    evidence = (
        sensor(
            "sensor.solver.left", "succeeded",
            quantity="solver.recompute", unit="none", tolerance=False,
        ),
        sensor(
            "sensor.solver.right", "failed",
            quantity="solver.recompute", unit="none", tolerance=False,
        ),
    )
    matrix = build_consistency_matrices(evidence)[0]
    cell = matrix.cell(*matrix.sensor_ids)

    assert cell.status is ConsistencyStatus.INCONSISTENT
    assert cell.maximum_error is None
    assert cell.allowed_error is None


def test_matrix_rejects_mixed_revisions_and_duplicate_evidence_ids():
    with pytest.raises(ValueError, match="same design revision"):
        build_consistency_matrices((
            sensor("sensor.width.r2", 45.0, design_revision=2),
            sensor("sensor.width.r3", 45.0, design_revision=3),
        ))
    duplicate = sensor("sensor.width.duplicate", 45.0)
    with pytest.raises(ValueError, match="ids must be unique"):
        build_consistency_matrices((duplicate, duplicate))


def test_adapted_r1_observations_feed_the_quantity_matrix():
    observations = ObservationSet(
        id="observations.matrix.r2",
        design_revision=2,
        feature_ir_sha256=HASH,
        observations=tuple(
            NumericObservation(
                id=f"observation.width.{layer.value}",
                quantity=GovernedQuantity.PLATE_WIDTH,
                source=ObservationSource(
                    layer=layer,
                    document_id=f"document.{layer.value}",
                    document_sha256=HASH,
                    backend_id=(
                        "freecad"
                        if layer is ObservationLayer.BREP_MEASUREMENT
                        else None
                    ),
                    backend_version=(
                        "1.1.0"
                        if layer is ObservationLayer.BREP_MEASUREMENT
                        else None
                    ),
                ),
                method=f"{layer.value} width",
                governing=layer is ObservationLayer.BREP_MEASUREMENT,
                value=45.0,
                unit=ObservationUnit.MILLIMETRE,
            )
            for layer in (
                ObservationLayer.ENGINEERING_INTENT,
                ObservationLayer.FEATURE_IR,
                ObservationLayer.BREP_MEASUREMENT,
            )
        ),
    )
    matrix = build_consistency_matrices(
        sensor_evidence_from_observation_set(observations)
    )[0]

    assert matrix.quantity == "plate_width"
    assert len(matrix.sensor_ids) == 3
    assert all(
        cell.status is ConsistencyStatus.CONSISTENT for cell in matrix.cells
    )
