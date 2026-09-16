"""Requirement predicates are executed from measured geometry on both R1 backends."""

from pathlib import Path

import pytest

from spec2cad.backends.freecad_worker import FreeCADWorkerUnavailable, discover_freecad_cmd
from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    Applicability,
    GovernedQuantity,
    GeometryReconciliationError,
    ObservationLayer,
    PredicateOutcome,
    ReconciliationClassification,
    classify_reconciliation,
    observe_requirement_predicates,
    reconcile_motor_geometry,
    reconcile_predicates,
)


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def revision(number):
    result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    return (
        result.latest if number == 1
        else repair(result, "widen_to_recommended", approved_by="predicate-test").latest
    )


def backend_observations(design, tmp_path, executable):
    document = compile_feature_ir(design.intent_graph)
    manifest = feature_ir_manifest(document)
    cadquery = CadQueryAdapter()
    cq_result = cadquery.build(BuildRequest(
        request_id=f"build:cadquery:predicate:r{design.revision}",
        backend_id="cadquery", feature_ir=document, feature_ir_manifest=manifest,
    ))
    freecad = FreeCADAdapter(tmp_path, executable=executable)
    fc_result = freecad.build(BuildRequest(
        request_id=f"build:freecad:predicate:r{design.revision}",
        backend_id="freecad", feature_ir=document, feature_ir_manifest=manifest,
    ))
    assert cq_result.status is fc_result.status is BuildStatus.SUCCEEDED
    from spec2cad.reconciliation import extract_motor_observations
    return (
        extract_motor_observations(
            design.intent_graph, document, cadquery.csg_for(cq_result.snapshot)
        ),
        extract_motor_observations(
            design.intent_graph, document, freecad.csg_for(fc_result.snapshot)
        ),
    )


@pytest.mark.parametrize(
    ("revision_number", "expected"),
    [(1, PredicateOutcome.FAIL), (2, PredicateOutcome.PASS)],
)
def test_real_backends_produce_identical_predicate_outcomes(
    revision_number, expected, tmp_path
):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    design = revision(revision_number)
    feature_ir = compile_feature_ir(design.intent_graph)
    left, right = backend_observations(design, tmp_path, executable)
    left_predicates = observe_requirement_predicates(left, design.intent_graph)
    right_predicates = observe_requirement_predicates(right, design.intent_graph)
    report = reconcile_predicates(
        left_predicates,
        right_predicates,
        feature_ir_sha256=feature_ir_manifest(feature_ir).content_sha256,
    )
    assert report.consistent
    assert {item.left_outcome for item in report.checks} == {expected}
    assert {item.right_outcome for item in report.checks} == {expected}
    assert max(
        abs(item.left_measured_value - item.right_measured_value)
        for item in report.checks
    ) <= 1e-7


def test_predicate_reconciliation_fails_closed_on_requirement_identity(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    design = revision(2)
    left, right = backend_observations(design, tmp_path, executable)
    left_predicates = observe_requirement_predicates(left, design.intent_graph)
    right_predicates = list(observe_requirement_predicates(right, design.intent_graph))
    right_predicates[0] = right_predicates[0].model_copy(
        update={"requirement_id": "requirement.different"}
    )
    with pytest.raises(GeometryReconciliationError, match="IDs differ"):
        reconcile_predicates(
            left_predicates,
            tuple(right_predicates),
            feature_ir_sha256=left.feature_ir_sha256,
        )


def test_all_reconciliation_classifications_are_distinct_and_fail_closed(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    design = revision(2)
    left, right = backend_observations(design, tmp_path, executable)
    geometry = reconcile_motor_geometry(left, right)
    predicate_report = reconcile_predicates(
        observe_requirement_predicates(left, design.intent_graph),
        observe_requirement_predicates(right, design.intent_graph),
        feature_ir_sha256=left.feature_ir_sha256,
    )
    assert classify_reconciliation(
        left, right, geometry, predicate_report
    ).classification is ReconciliationClassification.CONSISTENT

    identity_defect = right.model_copy(update={"feature_ir_sha256": "f" * 64})
    assert classify_reconciliation(
        left, identity_defect, geometry, predicate_report
    ).classification is ReconciliationClassification.PIPELINE_DEFECT

    divergent_check = geometry.checks[0].model_copy(update={"consistent": False})
    divergent_geometry = geometry.model_copy(
        update={"checks": (divergent_check, *geometry.checks[1:])}
    )
    assert classify_reconciliation(
        left, right, divergent_geometry, predicate_report
    ).classification is ReconciliationClassification.BACKEND_DIVERGENCE

    changed = []
    for item in right.observations:
        if (
            item.source.layer is ObservationLayer.NATIVE_STATE
            and item.quantity is GovernedQuantity.PLATE_WIDTH
        ):
            item = item.model_copy(update={"value": item.value + 0.02})
        changed.append(item)
    sensor_defect = right.model_copy(update={"observations": tuple(changed)})
    assert classify_reconciliation(
        left, sensor_defect, geometry, predicate_report
    ).classification is ReconciliationClassification.SENSOR_DISAGREEMENT

    unavailable = []
    for item in right.observations:
        if (
            item.source.layer is ObservationLayer.BREP_MEASUREMENT
            and item.quantity is GovernedQuantity.PLATE_WIDTH
        ):
            item = item.model_copy(update={
                "applicability": Applicability.UNSUPPORTED,
                "governing": False,
                "value": None,
                "reason": "test backend cannot measure width",
            })
        unavailable.append(item)
    unsupported = right.model_copy(update={"observations": tuple(unavailable)})
    assert classify_reconciliation(
        left, unsupported, geometry, predicate_report
    ).classification is ReconciliationClassification.UNSUPPORTED

    assert classify_reconciliation(
        left, right, None, predicate_report
    ).classification is ReconciliationClassification.NOT_ASSESSED
