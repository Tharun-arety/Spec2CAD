"""R2 disagreement localization follows explicit layer transitions."""

import pytest

from spec2cad.reconciliation import (
    DefectOrigin,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
    build_consistency_matrices,
    diagnose_inconsistencies,
)


HASH = "a" * 64
BACKEND_LAYERS = {
    SensorLayer.NATIVE_CONSTRAINT,
    SensorLayer.BREP_MEASUREMENT,
    SensorLayer.TOPOLOGY_RESULT,
    SensorLayer.SOLVER_STATE,
}


def sensor(sensor_id, layer, value):
    backend = "freecad" if layer in BACKEND_LAYERS else None
    return SensorEvidence(
        id=sensor_id,
        label=sensor_id,
        revision=1,
        design_revision=2,
        quantity="governed_width",
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
        tolerance=SensorTolerance(
            policy_id="policy.test",
            policy_version="1.0.0",
            unit="mm",
            absolute=0.01,
        ),
        method=SensorMethod(
            id="method.test",
            version="1.0.0",
            description="Localization test sensor.",
        ),
        release_role=(
            SensorReleaseRole.REFERENCE
            if layer in {
                SensorLayer.ENGINEERING_INTENT_EXPECTATION,
                SensorLayer.FEATURE_IR_VALUE,
            }
            else SensorReleaseRole.DIAGNOSTIC
        ),
    )


@pytest.mark.parametrize(
    ("left_layer", "right_layer", "origin"),
    [
        (
            SensorLayer.ENGINEERING_INTENT_EXPECTATION,
            SensorLayer.FEATURE_IR_VALUE,
            DefectOrigin.INTENT_COMPILATION,
        ),
        (
            SensorLayer.FEATURE_IR_VALUE,
            SensorLayer.NATIVE_CONSTRAINT,
            DefectOrigin.FEATURE_IR_LOWERING,
        ),
        (
            SensorLayer.NATIVE_CONSTRAINT,
            SensorLayer.BREP_MEASUREMENT,
            DefectOrigin.BACKEND_REALIZATION,
        ),
        (
            SensorLayer.FEATURE_IR_VALUE,
            SensorLayer.SOLVER_STATE,
            DefectOrigin.BACKEND_REALIZATION,
        ),
        (
            SensorLayer.TOPOLOGY_RESULT,
            SensorLayer.BREP_MEASUREMENT,
            DefectOrigin.TOPOLOGY,
        ),
        (
            SensorLayer.BREP_MEASUREMENT,
            SensorLayer.BREP_MEASUREMENT,
            DefectOrigin.MEASUREMENT,
        ),
        (
            SensorLayer.VISUAL_DIAGNOSTIC,
            SensorLayer.BREP_MEASUREMENT,
            DefectOrigin.VISUAL_INSPECTION,
        ),
    ],
)
def test_each_supported_layer_transition_has_a_bounded_origin(
    left_layer, right_layer, origin
):
    evidence = (
        sensor("sensor.left", left_layer, 1.0),
        sensor("sensor.right", right_layer, 2.0),
    )
    diagnoses = diagnose_inconsistencies(
        evidence, build_consistency_matrices(evidence)
    )

    assert len(diagnoses) == 1
    assert diagnoses[0].origin is origin
    assert diagnoses[0].advisory is (origin is DefectOrigin.VISUAL_INSPECTION)
    assert diagnoses[0].sensor_ids == ("sensor.left", "sensor.right")


def test_symmetric_matrix_cells_produce_one_deterministic_diagnosis():
    evidence = (
        sensor("sensor.z", SensorLayer.FEATURE_IR_VALUE, 1.0),
        sensor("sensor.a", SensorLayer.NATIVE_CONSTRAINT, 2.0),
    )
    diagnoses = diagnose_inconsistencies(
        tuple(reversed(evidence)), build_consistency_matrices(evidence)
    )

    assert len(diagnoses) == 1
    assert diagnoses[0].sensor_ids == ("sensor.a", "sensor.z")


def test_consistent_pairs_are_not_diagnosed_and_skipped_layers_are_unlocalized():
    consistent = (
        sensor("sensor.eig.same", SensorLayer.ENGINEERING_INTENT_EXPECTATION, 1.0),
        sensor("sensor.feature.same", SensorLayer.FEATURE_IR_VALUE, 1.0),
    )
    assert diagnose_inconsistencies(
        consistent, build_consistency_matrices(consistent)
    ) == ()

    skipped = (
        sensor("sensor.eig", SensorLayer.ENGINEERING_INTENT_EXPECTATION, 1.0),
        sensor("sensor.brep", SensorLayer.BREP_MEASUREMENT, 2.0),
    )
    diagnosis = diagnose_inconsistencies(
        skipped, build_consistency_matrices(skipped)
    )[0]
    assert diagnosis.origin is DefectOrigin.UNLOCALIZED


def test_missing_matrix_evidence_fails_closed():
    evidence = (
        sensor("sensor.left", SensorLayer.FEATURE_IR_VALUE, 1.0),
        sensor("sensor.right", SensorLayer.NATIVE_CONSTRAINT, 2.0),
    )
    matrices = build_consistency_matrices(evidence)
    with pytest.raises(ValueError, match="missing SensorEvidence"):
        diagnose_inconsistencies((evidence[0],), matrices)
