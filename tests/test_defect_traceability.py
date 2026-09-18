"""R2 defect traces resolve exact evidence into authoritative graph records."""

import hashlib
import json
from pathlib import Path

import pytest

from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import run
from spec2cad.reconciliation import (
    ResponsibilityNamespace,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
    build_consistency_matrices,
    diagnose_inconsistencies,
    trace_defect_responsibility,
)
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    CSGRelationship,
    GraphReference,
    ReferenceNamespace,
    RelationshipKind,
)
from tests.test_cad_state_graph_schema import observed_graph


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def model_hash(value) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def documents():
    revision = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    ).latest
    eig = revision.intent_graph
    feature_ir = compile_feature_ir(eig)
    parameter = next(item for item in feature_ir.parameters if item.name == "plate_width")
    pad = next(item for item in feature_ir.features if item.type == "pad")
    eig_id = parameter.intent_links[0].eig_node_id
    csg = ReferenceNamespace.CAD_STATE_GRAPH
    relationships = (
        CSGRelationship(
            id="rel.parameter.intent",
            kind=RelationshipKind.REALIZES_INTENT,
            source=GraphReference(namespace=csg, id="param.plate_width"),
            target=GraphReference(
                namespace=ReferenceNamespace.ENGINEERING_INTENT_GRAPH,
                id=eig_id,
            ),
        ),
        CSGRelationship(
            id="rel.pad.topology",
            kind=RelationshipKind.PRODUCES_TOPOLOGY,
            source=GraphReference(namespace=csg, id="feature.pad"),
            target=GraphReference(
                namespace=csg, id="topology.base_top_surface"
            ),
        ),
        CSGRelationship(
            id="rel.pad.intent",
            kind=RelationshipKind.REALIZES_INTENT,
            source=GraphReference(namespace=csg, id="feature.pad"),
            target=GraphReference(
                namespace=ReferenceNamespace.ENGINEERING_INTENT_GRAPH,
                id=pad.intent_links[0].eig_node_id,
            ),
        ),
        CSGRelationship(
            id="rel.pad.feature_ir",
            kind=RelationshipKind.REALIZES_FEATURE_IR,
            source=GraphReference(namespace=csg, id="feature.pad"),
            target=GraphReference(
                namespace=ReferenceNamespace.FEATURE_IR, id=pad.id,
            ),
        ),
        CSGRelationship(
            id="rel.parameter.feature_ir",
            kind=RelationshipKind.REALIZES_FEATURE_IR,
            source=GraphReference(namespace=csg, id="param.plate_width"),
            target=GraphReference(
                namespace=ReferenceNamespace.FEATURE_IR,
                id=parameter.id,
            ),
        ),
    )
    graph = observed_graph().model_copy(update={
        "source_feature_ir_sha256": feature_ir_manifest(feature_ir).content_sha256,
        "relationships": relationships,
    })
    return eig, feature_ir, CADStateGraph.model_validate(graph.model_dump()), parameter


def numeric_sensor(sensor_id, layer, record_id, value, *, eig, feature_ir, graph):
    if layer is SensorLayer.ENGINEERING_INTENT_EXPECTATION:
        document_id = f"eig.motor.r{eig.revision}"
        document_sha256 = model_hash(eig)
        backend_id = backend_version = None
    elif layer is SensorLayer.FEATURE_IR_VALUE:
        document_id = feature_ir.id
        document_sha256 = feature_ir_manifest(feature_ir).content_sha256
        backend_id = backend_version = None
    else:
        document_id = graph.id
        document_sha256 = csg_content_hash(graph)
        backend_id, backend_version = graph.backend_id, graph.backend_version
    return SensorEvidence(
        id=sensor_id,
        label=sensor_id,
        revision=1,
        design_revision=eig.revision,
        quantity="plate_width",
        source=SensorReference(
            layer=layer,
            document_id=document_id,
            document_sha256=document_sha256,
            record_ids=(record_id,),
            backend_id=backend_id,
            backend_version=backend_version,
        ),
        value=value,
        unit="mm",
        tolerance=SensorTolerance(
            policy_id="policy.test", policy_version="1.0.0",
            unit="mm", absolute=0.01,
        ),
        method=SensorMethod(
            id="method.test", version="1.0.0", description="Traceability test.",
        ),
        release_role=SensorReleaseRole.REFERENCE,
    )


def test_diagnosis_resolves_deterministically_across_all_three_graphs():
    eig, feature_ir, graph, parameter = documents()
    eig_id = parameter.intent_links[0].eig_node_id
    evidence = (
        numeric_sensor(
            "sensor.eig", SensorLayer.ENGINEERING_INTENT_EXPECTATION,
            eig_id, 40.0, eig=eig, feature_ir=feature_ir, graph=graph,
        ),
        numeric_sensor(
            "sensor.feature", SensorLayer.FEATURE_IR_VALUE,
            parameter.id, 41.0, eig=eig, feature_ir=feature_ir, graph=graph,
        ),
    )
    diagnoses = diagnose_inconsistencies(
        evidence, build_consistency_matrices(evidence)
    )

    traces = trace_defect_responsibility(
        diagnoses, tuple(reversed(evidence)),
        intent_graph=eig, feature_ir=feature_ir, cad_state_graphs=(graph,),
    )

    assert len(traces) == 1
    trace = traces[0]
    assert trace.complete
    assert trace.unresolved_references == ()
    assert trace.record_ids(ResponsibilityNamespace.ENGINEERING_INTENT_GRAPH) == (
        eig_id,
    )
    assert trace.record_ids(ResponsibilityNamespace.FEATURE_IR) == (parameter.id,)
    assert trace.record_ids(ResponsibilityNamespace.CAD_STATE_GRAPH) == (
        "param.plate_width",
    )
    assert any("direct_sensor" in link.bases for link in trace.links)
    assert any("csg_provenance" in link.bases for link in trace.links)


def test_nonvisual_missing_record_fails_closed_instead_of_guessing():
    eig, feature_ir, graph, parameter = documents()
    evidence = (
        numeric_sensor(
            "sensor.eig", SensorLayer.ENGINEERING_INTENT_EXPECTATION,
            "missing.dimension", 40.0,
            eig=eig, feature_ir=feature_ir, graph=graph,
        ),
        numeric_sensor(
            "sensor.feature", SensorLayer.FEATURE_IR_VALUE,
            parameter.id, 41.0,
            eig=eig, feature_ir=feature_ir, graph=graph,
        ),
    )
    diagnoses = diagnose_inconsistencies(
        evidence, build_consistency_matrices(evidence)
    )

    with pytest.raises(ValueError, match="missing EIG record"):
        trace_defect_responsibility(
            diagnoses, evidence, intent_graph=eig, feature_ir=feature_ir,
            cad_state_graphs=(graph,),
        )


def test_csg_topology_evidence_traverses_one_declared_owner_hop():
    eig, feature_ir, graph, _ = documents()
    evidence = (
        numeric_sensor(
            "sensor.measurement.a", SensorLayer.BREP_MEASUREMENT,
            "topology.base_top_surface", 40.0,
            eig=eig, feature_ir=feature_ir, graph=graph,
        ),
        numeric_sensor(
            "sensor.measurement.b", SensorLayer.BREP_MEASUREMENT,
            "topology.base_top_surface", 41.0,
            eig=eig, feature_ir=feature_ir, graph=graph,
        ),
    )
    diagnoses = diagnose_inconsistencies(
        evidence, build_consistency_matrices(evidence)
    )

    trace = trace_defect_responsibility(
        diagnoses, evidence, intent_graph=eig, feature_ir=feature_ir,
        cad_state_graphs=(graph,),
    )[0]

    assert trace.complete
    assert trace.record_ids(ResponsibilityNamespace.CAD_STATE_GRAPH) == (
        "feature.pad", "topology.base_top_surface",
    )
    assert any("csg_dependency" in link.bases for link in trace.links)


def test_visual_record_outside_authoritative_graphs_is_explicitly_incomplete():
    eig, feature_ir, graph, parameter = documents()
    measured = numeric_sensor(
        "sensor.measured", SensorLayer.BREP_MEASUREMENT,
        "param.plate_width", 40.0,
        eig=eig, feature_ir=feature_ir, graph=graph,
    )
    visual = measured.model_copy(update={
        "id": "sensor.visual",
        "source": SensorReference(
            layer=SensorLayer.VISUAL_DIAGNOSTIC,
            document_id="view.bundle.r1",
            document_sha256="f" * 64,
            record_ids=("view.front",),
        ),
        "value": 41.0,
        "release_role": SensorReleaseRole.DIAGNOSTIC,
    })
    evidence = (measured, visual)
    diagnoses = diagnose_inconsistencies(
        evidence, build_consistency_matrices(evidence)
    )

    trace = trace_defect_responsibility(
        diagnoses, evidence, intent_graph=eig, feature_ir=feature_ir,
        cad_state_graphs=(graph,),
    )[0]

    assert not trace.complete
    assert trace.advisory
    assert trace.unresolved_references[0].record_id == "view.front"
    assert "advisory visual" in trace.unresolved_references[0].reason
