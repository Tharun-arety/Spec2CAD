"""Semantic topology fingerprints exclude transient native identity."""

from pathlib import Path

import pytest

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import FreeCADWorkerUnavailable, discover_freecad_cmd
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import topology_fingerprints
from spec2cad.schemas.cad_state_graph import CADStateGraph, SemanticTopologyNode
from tests.test_cad_state_graph_schema import observed_graph


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def replace_topology(graph, topology):
    nodes = tuple(topology if node.id == topology.id else node for node in graph.nodes)
    return CADStateGraph.model_validate({**graph.model_dump(), "nodes": nodes})


def fingerprint_for(graph, topology_id="topology.base_top_surface"):
    return next(
        item for item in topology_fingerprints(graph)
        if item.source_topology_id == topology_id
    )


def test_fingerprint_is_canonical_and_round_trips():
    graph = observed_graph()
    fingerprint = fingerprint_for(graph)

    assert len(fingerprint.content_sha256) == 64
    assert fingerprint.source_csg_sha256 != fingerprint.content_sha256
    assert type(fingerprint).model_validate_json(
        fingerprint.model_dump_json()
    ) == fingerprint


def test_backend_native_identity_and_node_order_do_not_change_semantic_hash():
    graph = observed_graph()
    topology = next(
        node for node in graph.nodes if isinstance(node, SemanticTopologyNode)
    )
    renamed = topology.model_copy(update={
        "backend_native_id": "native:surface:unrelated",
    })
    other_backend = replace_topology(graph, renamed).model_copy(update={
        "backend_id": "cadquery",
        "backend_version": "2.7.0",
    })
    other_backend = CADStateGraph.model_validate({
        **other_backend.model_dump(),
        "nodes": tuple(reversed(other_backend.nodes)),
    })

    assert fingerprint_for(graph).content_sha256 == (
        fingerprint_for(other_backend).content_sha256
    )


def test_declared_quantization_absorbs_noise_but_detects_real_change():
    graph = observed_graph()
    topology = next(
        node for node in graph.nodes if isinstance(node, SemanticTopologyNode)
    )
    tiny_noise = topology.model_copy(update={
        "centroid_mm": (0.0000004, 0.0, 5.0),
    })
    changed = topology.model_copy(update={
        "centroid_mm": (0.02, 0.0, 5.0),
    })

    assert fingerprint_for(graph).content_sha256 == fingerprint_for(
        replace_topology(graph, tiny_noise)
    ).content_sha256
    assert fingerprint_for(graph).content_sha256 != fingerprint_for(
        replace_topology(graph, changed)
    ).content_sha256


def test_semantic_role_geometry_and_measurements_are_identity_inputs():
    graph = observed_graph()
    topology = next(
        node for node in graph.nodes if isinstance(node, SemanticTopologyNode)
    )
    changed_role = topology.model_copy(update={"semantic_role": "mounting_surface"})
    changed_geometry = topology.model_copy(update={"geometry_type": "cylinder"})
    measurement = topology.measurements[0].model_copy(update={"value": 2001.0})
    changed_measurement = topology.model_copy(update={"measurements": (measurement,)})
    baseline = fingerprint_for(graph).content_sha256

    assert fingerprint_for(replace_topology(graph, changed_role)).content_sha256 != baseline
    assert fingerprint_for(replace_topology(graph, changed_geometry)).content_sha256 != baseline
    assert fingerprint_for(
        replace_topology(graph, changed_measurement)
    ).content_sha256 != baseline


def test_real_backends_produce_matching_semantic_fingerprints(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    result = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    )
    revision = repair(
        result, "widen_to_recommended", approved_by="topology-fingerprint-test"
    ).latest
    feature_ir = compile_feature_ir(revision.intent_graph)
    manifest = feature_ir_manifest(feature_ir)
    cadquery = CadQueryAdapter()
    freecad = FreeCADAdapter(tmp_path, executable=executable)
    cq_result = cadquery.build(BuildRequest(
        request_id="build:cadquery:topology_fingerprint",
        backend_id="cadquery",
        feature_ir=feature_ir,
        feature_ir_manifest=manifest,
    ))
    fc_result = freecad.build(BuildRequest(
        request_id="build:freecad:topology_fingerprint",
        backend_id="freecad",
        feature_ir=feature_ir,
        feature_ir_manifest=manifest,
    ))
    assert cq_result.status is fc_result.status is BuildStatus.SUCCEEDED
    cq = {
        item.semantic_role: item
        for item in topology_fingerprints(cadquery.csg_for(cq_result.snapshot))
    }
    fc = {
        item.semantic_role: item
        for item in topology_fingerprints(freecad.csg_for(fc_result.snapshot))
    }

    assert cq.keys() == fc.keys()
    for role in cq:
        assert cq[role].model_dump(exclude={
            "id", "source_csg_id", "source_csg_sha256", "source_topology_id",
        }) == fc[role].model_dump(exclude={
            "id", "source_csg_id", "source_csg_sha256", "source_topology_id",
        })
