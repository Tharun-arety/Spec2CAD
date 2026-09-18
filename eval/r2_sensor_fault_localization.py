"""Execute deterministic benchmark B.R2 over typed injected fault evidence."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import discover_freecad_cmd
from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    Applicability,
    DefectOrigin,
    GoverningConsistencyStatus,
    SensorDiagnostic,
    SensorDiagnosticSeverity,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
    assess_governing_consistency,
    build_consistency_matrices,
    diagnose_inconsistencies,
    trace_defect_responsibility,
)
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    ConstraintObservation,
    RecomputeObservation,
)
from spec2cad.schemas.feature_ir import FeatureIR
from spec2cad.validation.gate import evaluate_release


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
REPORT = ROOT / "eval" / "r2_sensor_fault_localization_report.json"


def _model_hash(value) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _request(feature_ir: FeatureIR, purpose: str) -> BuildRequest:
    return BuildRequest(
        request_id=f"benchmark:b-r2:freecad:{purpose}",
        backend_id="freecad",
        feature_ir=feature_ir,
        feature_ir_manifest=feature_ir_manifest(feature_ir),
    )


def _normalized_graph(
    graph: CADStateGraph,
    *,
    graph_id: str | None = None,
    nodes=None,
) -> CADStateGraph:
    return CADStateGraph.model_validate(graph.model_copy(update={
        "id": graph_id or graph.id,
        "nodes": tuple(
            item for item in (nodes or graph.nodes) if item.kind != "artifact"
        ),
    }).model_dump())


def _faulty_feature_ir(feature_ir: FeatureIR) -> FeatureIR:
    parameter = next(
        item for item in feature_ir.parameters if item.name == "plate_width"
    )
    changed = parameter.model_copy(update={"value": parameter.value + 1.0})
    return FeatureIR.model_validate(feature_ir.model_copy(update={
        "parameters": tuple(
            changed if item.id == parameter.id else item
            for item in feature_ir.parameters
        )
    }).model_dump())


def _graph_with_node_update(
    graph: CADStateGraph,
    *,
    graph_id: str,
    node_id: str,
    update: dict,
) -> CADStateGraph:
    nodes = tuple(
        item.model_copy(update=update) if item.id == node_id else item
        for item in graph.nodes
    )
    return _normalized_graph(graph, graph_id=graph_id, nodes=nodes)


def _source(
    layer: SensorLayer,
    record_id: str,
    *,
    eig,
    feature_ir: FeatureIR,
    graph: CADStateGraph | None = None,
) -> SensorReference:
    if layer is SensorLayer.ENGINEERING_INTENT_EXPECTATION:
        return SensorReference(
            layer=layer,
            document_id=f"eig.motor.r{eig.revision}",
            document_sha256=_model_hash(eig),
            record_ids=(record_id,),
        )
    if layer is SensorLayer.FEATURE_IR_VALUE:
        return SensorReference(
            layer=layer,
            document_id=feature_ir.id,
            document_sha256=feature_ir_manifest(feature_ir).content_sha256,
            record_ids=(record_id,),
        )
    if layer is SensorLayer.VISUAL_DIAGNOSTIC:
        return SensorReference(
            layer=layer,
            document_id="view.bundle.b_r2",
            document_sha256=hashlib.sha256(b"B.R2 advisory view").hexdigest(),
            record_ids=(record_id,),
        )
    if graph is None:
        raise ValueError(f"{layer.value} requires a CAD State Graph")
    return SensorReference(
        layer=layer,
        document_id=graph.id,
        document_sha256=csg_content_hash(graph),
        record_ids=(record_id,),
        backend_id=graph.backend_id,
        backend_version=graph.backend_version,
    )


def _sensor(
    sensor_id: str,
    layer: SensorLayer,
    record_id: str,
    value,
    role: SensorReleaseRole,
    *,
    quantity: str,
    eig,
    feature_ir: FeatureIR,
    graph: CADStateGraph | None = None,
    applicability: Applicability = Applicability.APPLICABLE,
) -> SensorEvidence:
    categorical = isinstance(value, (bool, str)) or value is None and quantity.startswith(
        ("solver.", "topology.")
    )
    diagnostics = ()
    if applicability is not Applicability.APPLICABLE:
        diagnostics = (SensorDiagnostic(
            severity=SensorDiagnosticSeverity.WARNING,
            code="benchmark.not_assessed",
            message="B.R2 injected unavailable required sensor evidence.",
            related_record_ids=(record_id,),
        ),)
    return SensorEvidence(
        id=sensor_id,
        label=f"B.R2 {sensor_id}",
        revision=1,
        design_revision=eig.revision,
        quantity=quantity,
        source=_source(
            layer, record_id, eig=eig, feature_ir=feature_ir, graph=graph
        ),
        value=value,
        unit="none" if categorical else "mm",
        tolerance=(
            None
            if categorical or applicability is not Applicability.APPLICABLE
            else SensorTolerance(
                policy_id="policy.r1_cross_backend",
                policy_version="1.0.0",
                unit="mm",
                absolute=0.01,
            )
        ),
        method=SensorMethod(
            id=f"method.b_r2.{sensor_id.replace('sensor.', '').replace('.', '_')}",
            version="1.0.0",
            description="Deterministic B.R2 typed fault injection sensor.",
        ),
        applicability=applicability,
        release_role=role,
        diagnostics=diagnostics,
    )


def _measurement(node, name: str) -> float:
    return next(item.value for item in node.measurements if item.name == name)


def _case(
    fault: str,
    evidence: tuple[SensorEvidence, ...],
    target_pair: tuple[str, str],
    expected_origin: DefectOrigin | None,
    *,
    eig,
    feature_ir: FeatureIR,
    graphs: tuple[CADStateGraph, ...],
    intent,
    measured_reports,
    expected_consistency: str,
    expected_release: str,
) -> dict:
    matrices = build_consistency_matrices(evidence)
    matrix = next(item for item in matrices if set(target_pair) <= set(item.sensor_ids))
    ordered_pair = tuple(sorted(target_pair))
    consistency = matrix.cell(*ordered_pair).status.value
    diagnoses = diagnose_inconsistencies(evidence, matrices)
    primary = next(
        (item for item in diagnoses if item.sensor_ids == ordered_pair), None
    )
    traces = trace_defect_responsibility(
        diagnoses,
        evidence,
        intent_graph=eig,
        feature_ir=feature_ir,
        cad_state_graphs=graphs,
    ) if diagnoses else ()
    primary_trace = next(
        (item for item in traces if primary and item.diagnosis_id == primary.id), None
    )
    assessment = assess_governing_consistency(evidence, matrices)
    decision = evaluate_release(
        intent,
        measured_reports,
        governing_consistency=assessment,
    )
    origin = primary.origin if primary else None
    advisory = primary.advisory if primary else False
    expected_trace = expected_origin is not None and expected_origin is not DefectOrigin.VISUAL_INSPECTION
    passed = all((
        consistency == expected_consistency,
        origin is expected_origin,
        decision.status.value == expected_release,
        primary_trace is not None if expected_origin is not None else primary is None,
        primary_trace.complete if expected_trace and primary_trace else not expected_trace,
        advisory is (expected_origin is DefectOrigin.VISUAL_INSPECTION),
    ))
    return {
        "case_id": f"B.R2.{fault}",
        "fault": fault,
        "target_sensor_ids": list(ordered_pair),
        "consistency": consistency,
        "origin": origin.value if origin else None,
        "diagnosis_id": primary.id if primary else None,
        "trace_id": primary_trace.id if primary_trace else None,
        "trace_complete": primary_trace.complete if primary_trace else None,
        "advisory": advisory,
        "governing": assessment.governing,
        "assessment": assessment.status.value,
        "release": decision.status.value,
        "step_export_allowed": decision.step_export_allowed,
        "passed": passed,
    }


def run_benchmark(artifact_root: Path) -> dict:
    pipeline = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
        create_messages=False,
    )
    revision = repair(
        pipeline, "widen_to_recommended", approved_by="benchmark-b-r2"
    ).latest
    eig = revision.intent_graph
    feature_ir = compile_feature_ir(eig)
    faulty_feature_ir = _faulty_feature_ir(feature_ir)
    adapter = FreeCADAdapter(
        artifact_root / "freecad", executable=discover_freecad_cmd()
    )
    healthy_build = adapter.build(_request(feature_ir, "healthy"))
    compiler_build = adapter.build(_request(faulty_feature_ir, "compiler_fault"))
    if any(
        item.status is not BuildStatus.SUCCEEDED
        for item in (healthy_build, compiler_build)
    ):
        raise RuntimeError("B.R2 FreeCAD build failed")
    healthy = _normalized_graph(adapter.csg_for(healthy_build.snapshot))
    compiler_graph = _normalized_graph(adapter.csg_for(compiler_build.snapshot))

    width_parameter = next(
        item for item in feature_ir.parameters if item.name == "plate_width"
    )
    faulty_width_parameter = next(
        item for item in faulty_feature_ir.parameters if item.name == "plate_width"
    )
    width_intent_id = width_parameter.intent_links[0].eig_node_id
    eig_width = float(eig.node(width_intent_id).value)
    compiler_solid = next(
        item for item in compiler_graph.nodes
        if item.kind == "semantic_topology" and item.semantic_role == "part_solid"
    )

    parameter_node = next(
        item for item in healthy.nodes
        if item.kind == "parameter_expression" and item.parameter_name == "plate_width"
    )
    constraint_id = next(
        item.source.id for item in healthy.relationships
        if item.kind.value == "references"
        and item.target.id == parameter_node.id
    )
    constraint_node = next(item for item in healthy.nodes if item.id == constraint_id)
    constraint_graph = _graph_with_node_update(
        healthy,
        graph_id=f"{healthy.id}.fault.constraint",
        node_id=constraint_id,
        update={
            "value": float(constraint_node.value) + 1.0,
            "state": ConstraintObservation.VIOLATED,
        },
    )
    recompute_graph = _graph_with_node_update(
        healthy,
        graph_id=f"{healthy.id}.fault.recompute",
        node_id=healthy.root_document_id,
        update={"recompute": RecomputeObservation.FAILED},
    )
    topology_node = next(
        item for item in healthy.nodes
        if item.kind == "semantic_topology" and item.geometry_type == "cylinder"
    )
    topology_graph = _graph_with_node_update(
        healthy,
        graph_id=f"{healthy.id}.fault.topology",
        node_id=topology_node.id,
        update={"signature_sha256": "f" * 64},
    )
    solid = next(
        item for item in healthy.nodes
        if item.kind == "semantic_topology" and item.semantic_role == "part_solid"
    )
    changed_measurements = tuple(
        item.model_copy(update={"value": item.value + 1.0})
        if item.name == "width" else item
        for item in solid.measurements
    )
    measurement_graph = _graph_with_node_update(
        healthy,
        graph_id=f"{healthy.id}.fault.measurement",
        node_id=solid.id,
        update={"measurements": changed_measurements},
    )
    measured_width = _measurement(solid, "width")
    faulty_measured_width = _measurement(
        next(item for item in measurement_graph.nodes if item.id == solid.id),
        "width",
    )
    interface = feature_ir.interfaces[0]

    cases = []
    compiler_evidence = (
        _sensor(
            "sensor.compiler.eig", SensorLayer.ENGINEERING_INTENT_EXPECTATION,
            width_intent_id, eig_width, SensorReleaseRole.REFERENCE,
            quantity="plate_width", eig=eig, feature_ir=faulty_feature_ir,
        ),
        _sensor(
            "sensor.compiler.feature_ir", SensorLayer.FEATURE_IR_VALUE,
            faulty_width_parameter.id, faulty_width_parameter.value,
            SensorReleaseRole.REFERENCE, quantity="plate_width", eig=eig,
            feature_ir=faulty_feature_ir,
        ),
        _sensor(
            "sensor.compiler.brep", SensorLayer.BREP_MEASUREMENT,
            compiler_solid.id, _measurement(compiler_solid, "width"),
            SensorReleaseRole.GOVERNING, quantity="plate_width", eig=eig,
            feature_ir=faulty_feature_ir, graph=compiler_graph,
        ),
    )
    cases.append(_case(
        "compiler", compiler_evidence,
        ("sensor.compiler.eig", "sensor.compiler.feature_ir"),
        DefectOrigin.INTENT_COMPILATION,
        eig=eig, feature_ir=faulty_feature_ir, graphs=(compiler_graph,),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="inconsistent", expected_release="blocked",
    ))

    constraint_evidence = (
        _sensor(
            "sensor.constraint.feature_ir", SensorLayer.FEATURE_IR_VALUE,
            width_parameter.id, width_parameter.value, SensorReleaseRole.REFERENCE,
            quantity="plate_width", eig=eig, feature_ir=feature_ir,
        ),
        _sensor(
            "sensor.constraint.native", SensorLayer.NATIVE_CONSTRAINT,
            constraint_id, float(constraint_node.value) + 1.0,
            SensorReleaseRole.GOVERNING, quantity="plate_width", eig=eig,
            feature_ir=feature_ir, graph=constraint_graph,
        ),
    )
    cases.append(_case(
        "constraint", constraint_evidence,
        ("sensor.constraint.feature_ir", "sensor.constraint.native"),
        DefectOrigin.FEATURE_IR_LOWERING,
        eig=eig, feature_ir=feature_ir, graphs=(constraint_graph,),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="inconsistent", expected_release="blocked",
    ))

    recompute_evidence = (
        _sensor(
            "sensor.recompute.expected", SensorLayer.FEATURE_IR_VALUE,
            feature_ir.part.id, "succeeded", SensorReleaseRole.REFERENCE,
            quantity="solver.recompute", eig=eig, feature_ir=feature_ir,
        ),
        _sensor(
            "sensor.recompute.actual", SensorLayer.SOLVER_STATE,
            recompute_graph.root_document_id, "failed", SensorReleaseRole.GOVERNING,
            quantity="solver.recompute", eig=eig, feature_ir=feature_ir,
            graph=recompute_graph,
        ),
    )
    cases.append(_case(
        "recompute", recompute_evidence,
        ("sensor.recompute.expected", "sensor.recompute.actual"),
        DefectOrigin.BACKEND_REALIZATION,
        eig=eig, feature_ir=feature_ir, graphs=(recompute_graph,),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="inconsistent", expected_release="blocked",
    ))

    topology_evidence = (
        _sensor(
            "sensor.topology.expected", SensorLayer.FEATURE_IR_VALUE,
            interface.id, topology_node.signature_sha256,
            SensorReleaseRole.REFERENCE, quantity="topology.interface",
            eig=eig, feature_ir=feature_ir,
        ),
        _sensor(
            "sensor.topology.actual", SensorLayer.TOPOLOGY_RESULT,
            topology_node.id, "f" * 64, SensorReleaseRole.GOVERNING,
            quantity="topology.interface", eig=eig, feature_ir=feature_ir,
            graph=topology_graph,
        ),
    )
    cases.append(_case(
        "topology", topology_evidence,
        ("sensor.topology.expected", "sensor.topology.actual"),
        DefectOrigin.TOPOLOGY,
        eig=eig, feature_ir=feature_ir, graphs=(topology_graph,),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="inconsistent", expected_release="blocked",
    ))

    measurement_evidence = (
        _sensor(
            "sensor.measurement.reference", SensorLayer.BREP_MEASUREMENT,
            solid.id, measured_width, SensorReleaseRole.REFERENCE,
            quantity="plate_width", eig=eig, feature_ir=feature_ir, graph=healthy,
        ),
        _sensor(
            "sensor.measurement.governing", SensorLayer.BREP_MEASUREMENT,
            solid.id, faulty_measured_width, SensorReleaseRole.GOVERNING,
            quantity="plate_width", eig=eig, feature_ir=feature_ir,
            graph=measurement_graph,
        ),
    )
    cases.append(_case(
        "measurement", measurement_evidence,
        ("sensor.measurement.reference", "sensor.measurement.governing"),
        DefectOrigin.MEASUREMENT,
        eig=eig, feature_ir=feature_ir, graphs=(healthy, measurement_graph),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="inconsistent", expected_release="blocked",
    ))

    visual_evidence = (
        _sensor(
            "sensor.visual.reference", SensorLayer.FEATURE_IR_VALUE,
            width_parameter.id, width_parameter.value, SensorReleaseRole.REFERENCE,
            quantity="plate_width", eig=eig, feature_ir=feature_ir,
        ),
        _sensor(
            "sensor.visual.governing", SensorLayer.BREP_MEASUREMENT,
            solid.id, measured_width, SensorReleaseRole.GOVERNING,
            quantity="plate_width", eig=eig, feature_ir=feature_ir, graph=healthy,
        ),
        _sensor(
            "sensor.visual.false_positive", SensorLayer.VISUAL_DIAGNOSTIC,
            "view.front", measured_width + 1.0, SensorReleaseRole.DIAGNOSTIC,
            quantity="plate_width", eig=eig, feature_ir=feature_ir,
        ),
    )
    cases.append(_case(
        "visual_false_positive", visual_evidence,
        ("sensor.visual.governing", "sensor.visual.false_positive"),
        DefectOrigin.VISUAL_INSPECTION,
        eig=eig, feature_ir=feature_ir, graphs=(healthy,),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="inconsistent", expected_release="authorised",
    ))

    unavailable_evidence = (
        _sensor(
            "sensor.unavailable.reference", SensorLayer.FEATURE_IR_VALUE,
            width_parameter.id, None, SensorReleaseRole.REFERENCE,
            quantity="plate_width", eig=eig, feature_ir=feature_ir,
            applicability=Applicability.NOT_ASSESSED,
        ),
        _sensor(
            "sensor.unavailable.governing", SensorLayer.BREP_MEASUREMENT,
            solid.id, measured_width, SensorReleaseRole.GOVERNING,
            quantity="plate_width", eig=eig, feature_ir=feature_ir, graph=healthy,
        ),
    )
    cases.append(_case(
        "unavailable_sensor", unavailable_evidence,
        ("sensor.unavailable.reference", "sensor.unavailable.governing"),
        None,
        eig=eig, feature_ir=feature_ir, graphs=(healthy,),
        intent=revision.intent, measured_reports=revision.measured,
        expected_consistency="not_assessed", expected_release="blocked",
    ))

    return {
        "schema_version": "1.0.0",
        "benchmark": "B.R2",
        "scope": (
            "motor-adapter bounded typed fault injection; visual inspection "
            "remains advisory"
        ),
        "design_revision": eig.revision,
        "feature_ir_sha256": feature_ir_manifest(feature_ir).content_sha256,
        "freecad_version": adapter.descriptor.backend_version,
        "cases": cases,
        "all_passed": all(item["passed"] for item in cases),
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cadaico-b-r2-") as directory:
        report = run_benchmark(Path(directory))
    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"B.R2: {'PASS' if report['all_passed'] else 'FAIL'} -> {REPORT}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
