"""Both real R1 backends agree on governed motor geometry."""

from pathlib import Path

import pytest

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import FreeCADWorkerUnavailable, discover_freecad_cmd
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    Applicability,
    GovernedQuantity,
    GeometryReconciliationError,
    ObservationLayer,
    extract_motor_observations,
    reconcile_motor_geometry,
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
        else repair(result, "widen_to_recommended", approved_by="reconcile-test").latest
    )


def backend_observations(revision, tmp_path, executable):
    document = compile_feature_ir(revision.intent_graph)
    manifest = feature_ir_manifest(document)
    cadquery = CadQueryAdapter()
    cq_result = cadquery.build(BuildRequest(
        request_id=f"build:cadquery:motor:r{revision.revision}",
        backend_id="cadquery",
        feature_ir=document,
        feature_ir_manifest=manifest,
    ))
    freecad = FreeCADAdapter(tmp_path, executable=executable)
    fc_result = freecad.build(BuildRequest(
        request_id=f"build:freecad:motor:r{revision.revision}",
        backend_id="freecad",
        feature_ir=document,
        feature_ir_manifest=manifest,
    ))
    assert cq_result.status is fc_result.status is BuildStatus.SUCCEEDED
    return (
        extract_motor_observations(
            revision.intent_graph, document, cadquery.csg_for(cq_result.snapshot)
        ),
        extract_motor_observations(
            revision.intent_graph, document, freecad.csg_for(fc_result.snapshot)
        ),
    )


@pytest.mark.parametrize("revision_number", [1, 2])
def test_real_backends_reconcile_all_governed_geometry(revision_number, tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    cadquery, freecad = backend_observations(
        revision(revision_number), tmp_path, executable
    )
    report = reconcile_motor_geometry(cadquery, freecad)
    assert len(report.checks) == 10
    assert {item.quantity for item in report.checks} == {
        GovernedQuantity.PLATE_WIDTH,
        GovernedQuantity.PLATE_HEIGHT,
        GovernedQuantity.PLATE_THICKNESS,
        GovernedQuantity.OPENING_DIAMETER,
        GovernedQuantity.MOUNTING_DIAMETER,
        GovernedQuantity.MOUNTING_HOLE_CENTERS,
        GovernedQuantity.HOLE_SPACING_X,
        GovernedQuantity.HOLE_SPACING_Y,
        GovernedQuantity.VOLUME,
        GovernedQuantity.INTERFACE_GEOMETRY,
    }
    assert report.consistent
    assert max(item.maximum_absolute_error for item in report.checks) <= max(
        item.allowed_error for item in report.checks
    )
    cq_native = [
        item for item in cadquery.observations
        if item.source.layer is ObservationLayer.NATIVE_STATE
    ]
    fc_native = [
        item for item in freecad.observations
        if item.source.layer is ObservationLayer.NATIVE_STATE
    ]
    assert all(item.applicability is Applicability.UNSUPPORTED for item in cq_native)
    assert all(item.applicability is Applicability.APPLICABLE for item in fc_native)


def test_tolerance_breach_and_feature_identity_mismatch_fail_closed(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    left, right = backend_observations(revision(2), tmp_path, executable)
    changed = []
    for item in right.observations:
        if (
            item.source.layer is ObservationLayer.BREP_MEASUREMENT
            and item.quantity is GovernedQuantity.PLATE_WIDTH
        ):
            item = item.model_copy(update={"value": item.value + 0.02})
        changed.append(item)
    divergent = right.model_copy(update={"observations": tuple(changed)})
    report = reconcile_motor_geometry(left, divergent)
    width = next(
        item for item in report.checks
        if item.quantity is GovernedQuantity.PLATE_WIDTH
    )
    assert width.consistent is False
    assert report.consistent is False

    mismatched = right.model_copy(update={"feature_ir_sha256": "f" * 64})
    with pytest.raises(GeometryReconciliationError, match="same Feature IR"):
        reconcile_motor_geometry(left, mismatched)
