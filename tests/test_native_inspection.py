"""R2 native inspection reports health without inferring design authority."""

from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.reconciliation import (
    NativeInspectionKind,
    NativeInspectionStatus,
    inspect_native_health,
)
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    ConstraintNode,
    ConstraintObservation,
    DiagnosticNode,
    DiagnosticSeverity,
    RecomputeObservation,
    SketchNode,
)
from tests.test_cad_state_graph_schema import observed_graph


def replace_nodes(graph, replacements, additions=()):
    nodes = tuple(replacements.get(node.id, node) for node in graph.nodes) + additions
    return CADStateGraph.model_validate({**graph.model_dump(), "nodes": nodes})


def test_healthy_editable_graph_passes_every_native_health_check():
    graph = observed_graph()
    report = inspect_native_health(graph, design_revision=2)

    assert {item.kind for item in report.findings} == set(NativeInspectionKind)
    assert all(item.status is NativeInspectionStatus.PASS for item in report.findings)
    assert report.csg_sha256 == csg_content_hash(graph)
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_native_faults_are_detected_and_tied_to_exact_csg_records():
    graph = observed_graph()
    document = next(node for node in graph.nodes if node.kind == "document")
    sketch = next(node for node in graph.nodes if isinstance(node, SketchNode))
    constraint = next(node for node in graph.nodes if isinstance(node, ConstraintNode))
    redundant = constraint.model_copy(update={
        "state": ConstraintObservation.REDUNDANT,
    })
    conflicting = constraint.model_copy(update={
        "id": "constraint.base_width_conflict",
        "label": "Conflicting base width",
        "state": ConstraintObservation.VIOLATED,
    })
    bad_sketch = sketch.model_copy(update={
        "fully_constrained": False,
        "degrees_of_freedom": 2,
        "constraint_ids": (*sketch.constraint_ids, conflicting.id),
    })
    broken = DiagnosticNode(
        id="diagnostic.broken_reference",
        label="Broken reference",
        severity=DiagnosticSeverity.ERROR,
        code="broken_reference",
        message="A native feature references a missing support.",
        related_node_ids=(sketch.id,),
    )
    failed_document = document.model_copy(update={
        "recompute": RecomputeObservation.FAILED,
    })
    graph = replace_nodes(
        graph,
        {
            document.id: failed_document,
            sketch.id: bad_sketch,
            constraint.id: redundant,
        },
        additions=(conflicting, broken),
    )
    report = inspect_native_health(graph, design_revision=2)
    failures = [
        item for item in report.findings
        if item.status is NativeInspectionStatus.FAIL
    ]

    assert {item.kind for item in failures} == set(NativeInspectionKind)
    assert any(conflicting.id in item.csg_record_ids for item in failures)
    assert any(broken.id in item.csg_record_ids for item in failures)
    assert all(item.csg_record_ids for item in failures)


def test_unknown_native_state_is_not_assessed_never_false_success():
    graph = observed_graph()
    document = next(node for node in graph.nodes if node.kind == "document")
    sketch = next(node for node in graph.nodes if isinstance(node, SketchNode))
    constraint = next(node for node in graph.nodes if isinstance(node, ConstraintNode))
    graph = replace_nodes(graph, {
        document.id: document.model_copy(update={
            "recompute": RecomputeObservation.PENDING,
        }),
        sketch.id: sketch.model_copy(update={
            "fully_constrained": None,
            "degrees_of_freedom": None,
        }),
        constraint.id: constraint.model_copy(update={
            "state": ConstraintObservation.UNKNOWN,
        }),
    })
    report = inspect_native_health(graph, design_revision=2)
    by_kind = {}
    for finding in report.findings:
        by_kind.setdefault(finding.kind, []).append(finding.status)

    assert by_kind[NativeInspectionKind.SKETCH_DOF] == [
        NativeInspectionStatus.NOT_ASSESSED
    ]
    assert by_kind[NativeInspectionKind.REDUNDANT_CONSTRAINT] == [
        NativeInspectionStatus.NOT_ASSESSED
    ]
    assert by_kind[NativeInspectionKind.CONFLICTING_CONSTRAINT] == [
        NativeInspectionStatus.NOT_ASSESSED
    ]
    assert by_kind[NativeInspectionKind.RECOMPUTE] == [
        NativeInspectionStatus.NOT_ASSESSED
    ]


def test_noneditable_backend_reports_missing_native_checks_as_not_assessed():
    graph = observed_graph()
    document = next(node for node in graph.nodes if node.kind == "document")
    body = next(node for node in graph.nodes if node.kind == "body")
    feature = next(node for node in graph.nodes if node.kind == "native_feature")
    retained = tuple(
        node for node in graph.nodes
        if node.kind not in {"sketch", "sketch_geometry", "constraint"}
    )
    changed_document = document.model_copy(update={"editable": False})
    changed_body = body.model_copy(update={
        "feature_ids": tuple(
            item for item in body.feature_ids if not item.startswith("sketch.")
        ),
    })
    changed_feature = feature.model_copy(update={
        "input_ids": tuple(
            item for item in feature.input_ids if not item.startswith("sketch.")
        ),
    })
    retained = tuple(
        changed_document if node.id == document.id
        else changed_body if node.id == body.id
        else changed_feature if node.id == feature.id
        else node
        for node in retained
    )
    graph = CADStateGraph.model_validate({**graph.model_dump(), "nodes": retained})
    report = inspect_native_health(graph, design_revision=2)

    for kind in (
        NativeInspectionKind.SKETCH_DOF,
        NativeInspectionKind.REDUNDANT_CONSTRAINT,
        NativeInspectionKind.CONFLICTING_CONSTRAINT,
        NativeInspectionKind.BROKEN_REFERENCE,
    ):
        assert report.findings_of(kind)[0].status is (
            NativeInspectionStatus.NOT_ASSESSED
        )
