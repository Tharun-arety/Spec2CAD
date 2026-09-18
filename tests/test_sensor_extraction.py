"""R2.1.2 populates every sensor layer without escalating authority."""

from pathlib import Path

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    Applicability,
    GovernedQuantity,
    InterfaceGeometryObservation,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    ObservationSource,
    ObservationUnit,
    Point2D,
    PointSetObservation,
    PredicateObservation,
    PredicateOutcome,
    SensorLayer,
    SensorReleaseRole,
    csg_health_sensor_evidence,
    sensor_evidence_from_observation_set,
    visual_diagnostic_evidence,
)
from tests.test_cad_state_graph_schema import observed_graph


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
HASH = "a" * 64


def source(layer: ObservationLayer, *, backend: str | None = None):
    return ObservationSource(
        layer=layer,
        document_id=f"document.{layer.value}",
        document_sha256=HASH,
        backend_id=backend,
        backend_version="1.0.0" if backend else None,
    )


def test_existing_observation_layers_map_without_authority_escalation():
    observations = tuple(
        NumericObservation(
            id=f"observation.width.{layer.value}",
            quantity=GovernedQuantity.PLATE_WIDTH,
            source=source(
                layer,
                backend=(
                    "freecad"
                    if layer in {
                        ObservationLayer.NATIVE_STATE,
                        ObservationLayer.BREP_MEASUREMENT,
                    }
                    else None
                ),
            ),
            method=f"{layer.value} width",
            governing=layer in {
                ObservationLayer.NATIVE_STATE,
                ObservationLayer.BREP_MEASUREMENT,
            },
            value=45.0,
            unit=ObservationUnit.MILLIMETRE,
        )
        for layer in ObservationLayer
    )
    adapted = sensor_evidence_from_observation_set(ObservationSet(
        id="observations.motor.r2",
        design_revision=2,
        feature_ir_sha256=HASH,
        observations=observations,
    ))

    assert {item.source.layer for item in adapted} == {
        SensorLayer.ENGINEERING_INTENT_EXPECTATION,
        SensorLayer.FEATURE_IR_VALUE,
        SensorLayer.NATIVE_CONSTRAINT,
        SensorLayer.BREP_MEASUREMENT,
    }
    by_layer = {item.source.layer: item for item in adapted}
    assert by_layer[SensorLayer.ENGINEERING_INTENT_EXPECTATION].release_role is (
        SensorReleaseRole.REFERENCE
    )
    assert by_layer[SensorLayer.FEATURE_IR_VALUE].release_role is (
        SensorReleaseRole.REFERENCE
    )
    assert by_layer[SensorLayer.NATIVE_CONSTRAINT].release_role is (
        SensorReleaseRole.GOVERNING
    )
    assert by_layer[SensorLayer.BREP_MEASUREMENT].release_role is (
        SensorReleaseRole.GOVERNING
    )


def test_structured_and_unavailable_observations_retain_meaning():
    measured = source(ObservationLayer.BREP_MEASUREMENT, backend="freecad")
    points = tuple(
        Point2D(x_mm=x, y_mm=y)
        for x in (-15.5, 15.5)
        for y in (-15.5, 15.5)
    )
    bundle = ObservationSet(
        id="observations.structured.r2",
        design_revision=2,
        feature_ir_sha256=HASH,
        observations=(
            PointSetObservation(
                id="observation.mounting_centers.freecad",
                source=measured,
                method="cylindrical axes",
                governing=True,
                points=points,
            ),
            InterfaceGeometryObservation(
                id="observation.interface.freecad",
                source=measured,
                method="semantic interface surfaces",
                governing=True,
                opening_diameter_mm=22.5,
                mounting_diameter_mm=3.4,
                mounting_centers=points,
            ),
            PredicateObservation(
                id="observation.clearance.freecad",
                source=measured,
                method="compiled predicate",
                governing=True,
                requirement_id="requirement.clearance",
                outcome=PredicateOutcome.PASS,
                measured_value=5.3,
                threshold=4.0,
            ),
            NumericObservation(
                id="observation.volume.unavailable",
                quantity=GovernedQuantity.VOLUME,
                source=source(ObservationLayer.NATIVE_STATE, backend="cadquery"),
                applicability=Applicability.UNSUPPORTED,
                method="native volume",
                reason="native value unavailable",
                value=None,
                unit=ObservationUnit.CUBIC_MILLIMETRE,
            ),
        ),
    )
    adapted = sensor_evidence_from_observation_set(bundle)

    assert adapted[0].value == tuple(
        coordinate
        for point in points
        for coordinate in (point.x_mm, point.y_mm)
    )
    assert adapted[1].value[:2] == (22.5, 3.4)
    assert adapted[2].value == "pass"
    assert adapted[2].unit == "none"
    assert adapted[3].applicability is Applicability.UNSUPPORTED
    assert adapted[3].value is None
    assert adapted[3].diagnostics[0].message == "native value unavailable"


def test_csg_health_sources_cover_constraint_topology_and_solver_layers():
    graph = observed_graph()
    evidence = csg_health_sensor_evidence(graph, design_revision=2)

    assert {item.source.layer for item in evidence} == {
        SensorLayer.NATIVE_CONSTRAINT,
        SensorLayer.TOPOLOGY_RESULT,
        SensorLayer.SOLVER_STATE,
    }
    assert all(item.release_role is SensorReleaseRole.DIAGNOSTIC for item in evidence)
    assert all(item.source.document_sha256 == csg_content_hash(graph) for item in evidence)
    assert any(item.quantity == "solver.recompute" for item in evidence)
    assert any(item.quantity == "solver.sketch_degrees_of_freedom" for item in evidence)
    assert any(item.quantity == "topology.base_top_surface" for item in evidence)


def test_visual_diagnostic_supports_finding_and_truthful_not_assessed_state():
    finding = visual_diagnostic_evidence(
        id="sensor.visual.opening",
        label="Opening visible in canonical view",
        revision=1,
        design_revision=2,
        quantity="opening_presence",
        document_id="artifact.preview",
        document_sha256=HASH,
        record_ids=("artifact.preview",),
        method_id="method.visual_classifier",
        method_version="0.1.0",
        method_description="Advisory canonical-view classifier.",
        value=True,
    )
    unavailable = visual_diagnostic_evidence(
        id="sensor.visual.not_assessed",
        label="Visual diagnostic unavailable",
        revision=1,
        design_revision=2,
        quantity="visual_health",
        document_id="artifact.preview",
        document_sha256=HASH,
        record_ids=("artifact.preview",),
        method_id="method.visual_classifier",
        method_version="0.1.0",
        method_description="Advisory canonical-view classifier.",
        value=None,
        applicability=Applicability.NOT_ASSESSED,
        reason="No benchmarked visual classifier is configured.",
    )

    assert finding.source.layer is SensorLayer.VISUAL_DIAGNOSTIC
    assert finding.release_role is SensorReleaseRole.DIAGNOSTIC
    assert unavailable.value is None
    assert unavailable.diagnostics[0].code == "sensor.not_assessed"


def test_real_motor_observations_adapt_without_losing_records():
    result = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    )
    revision = repair(
        result,
        "widen_to_recommended",
        approved_by="sensor-extraction-test",
    ).latest
    feature_ir = compile_feature_ir(revision.intent_graph)
    adapter = CadQueryAdapter()
    built = adapter.build(BuildRequest(
        request_id="build:cadquery:sensor_extraction",
        backend_id="cadquery",
        feature_ir=feature_ir,
        feature_ir_manifest=feature_ir_manifest(feature_ir),
    ))
    assert built.status is BuildStatus.SUCCEEDED

    from spec2cad.reconciliation import extract_motor_observations

    observations = extract_motor_observations(
        revision.intent_graph,
        feature_ir,
        adapter.csg_for(built.snapshot),
    )
    adapted = sensor_evidence_from_observation_set(observations)

    assert len(adapted) == len(observations.observations)
    assert {item.id for item in adapted} == {
        item.id.replace("observation.", "sensor.", 1)
        for item in observations.observations
    }
    assert all(item.design_revision == revision.revision for item in adapted)
    csg_ids = {item.id for item in adapter.csg_for(built.snapshot).nodes}
    backend_layers = {
        SensorLayer.NATIVE_CONSTRAINT,
        SensorLayer.BREP_MEASUREMENT,
    }
    assert all(
        set(item.source.record_ids) <= csg_ids
        for item in adapted
        if item.source.layer in backend_layers
    )
