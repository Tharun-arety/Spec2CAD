"""R1H proves bounded breadth with unrelated structural compositions."""

from pathlib import Path

import pytest

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import FreeCADWorkerUnavailable, discover_freecad_cmd
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.fusion.graph_builder import build_intent_graph
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    ClassifiedReconciliation,
    ReconciliationClassification,
)
from spec2cad.schemas.evidence import (
    Authority,
    Evidence,
    EvidenceKind,
    EvidenceSet,
    ExtractionMethod,
    SemanticTarget,
    SourceModality,
    SourceRef,
)


ROOT = Path(__file__).resolve().parents[1]


def _cylindrical_feature_ir(name: str, *, wall: float | None):
    source = SourceRef(file=f"{name}.txt", modality=SourceModality.REQUIREMENT_TEXT)
    facts = [
        (SemanticTarget.PART_TYPE, EvidenceKind.FEATURE_CALLOUT, name, None),
        (SemanticTarget.OUTER_DIAMETER, EvidenceKind.DIAMETER, 28.0, "mm"),
        (SemanticTarget.BODY_LENGTH, EvidenceKind.LINEAR_DIMENSION, 36.0, "mm"),
    ]
    if wall is not None:
        facts.append((
            SemanticTarget.WALL_THICKNESS,
            EvidenceKind.LINEAR_DIMENSION,
            wall,
            "mm",
        ))
    evidence = EvidenceSet(items=[
        Evidence(
            id=f"ev_{name}_{target.value}", entity=name, kind=kind,
            target=target, value=value, unit=unit, source=source,
            extraction_method=ExtractionMethod.RULE_PARSER,
            confidence=1.0, authority=Authority.DEFINITIVE,
            is_explicit_annotation=True,
        )
        for target, kind, value, unit in facts
    ])
    graph, _ = build_intent_graph(evidence, part_name=name)
    return compile_feature_ir(graph)


def _families():
    motor = run(
        ROOT / "examples/motor_adapter/sketch.png",
        ROOT / "examples/motor_adapter/motor_datasheet.pdf",
        ROOT / "examples/motor_adapter/requirement.txt",
        backend_override="fixture",
    )
    motor = repair(motor, "widen_to_recommended", approved_by="r1h-test").latest
    bracket = run(
        requirement=ROOT / "examples/mounting_bracket/requirement.txt"
    ).latest
    return {
        "interface_plate": compile_feature_ir(motor.intent_graph),
        "slotted_bracket": compile_feature_ir(bracket.intent_graph),
        "solid_cylinder": _cylindrical_feature_ir("solid_cylinder", wall=None),
        "hollow_tube": _cylindrical_feature_ir("hollow_tube", wall=3.0),
    }


def test_four_unrelated_compositions_lower_and_build_in_cadquery(tmp_path):
    adapter = CadQueryAdapter(tmp_path)
    results = {}
    for name, document in _families().items():
        build = adapter.build(BuildRequest(
            request_id=f"build:cadquery:r1h:{name}", backend_id="cadquery",
            feature_ir=document, feature_ir_manifest=feature_ir_manifest(document),
        ))
        results[name] = build.status
        assert build.status is BuildStatus.SUCCEEDED, build.diagnostics
        graph = adapter.csg_for(build.snapshot)
        assert next(
            node for node in graph.nodes
            if node.kind == "semantic_topology" and node.semantic_role == "part_solid"
        ).measurements
    assert set(results) == {
        "interface_plate", "slotted_bracket", "solid_cylinder", "hollow_tube",
    }


def test_four_unrelated_compositions_build_as_native_freecad(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    adapter = FreeCADAdapter(tmp_path, executable=executable)
    for name, document in _families().items():
        build = adapter.build(BuildRequest(
            request_id=f"build:freecad:r1h:{name}", backend_id="freecad",
            feature_ir=document, feature_ir_manifest=feature_ir_manifest(document),
        ))
        assert build.status is BuildStatus.SUCCEEDED, (name, build.diagnostics)
        assert len(build.artifacts) == 3


def test_topology_affecting_slot_count_edit_uses_feature_ir_identity(tmp_path):
    try:
        executable = discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    document = _families()["slotted_bracket"]
    count = next(item for item in document.parameters if item.name == "slot_count")
    adapter = FreeCADAdapter(tmp_path, executable=executable)
    initial = adapter.build(BuildRequest(
        request_id="build:freecad:r1h:slot-count:before", backend_id="freecad",
        feature_ir=document, feature_ir_manifest=feature_ir_manifest(document),
    ))
    updated_count = count.model_copy(update={"value": count.value + 1})
    updated = document.model_copy(update={
        "parameters": tuple(
            updated_count if item.id == count.id else item
            for item in document.parameters
        )
    })
    edited = adapter.edit_parameter(
        initial.snapshot,
        BuildRequest(
            request_id="build:freecad:r1h:slot-count:after", backend_id="freecad",
            feature_ir=updated, feature_ir_manifest=feature_ir_manifest(updated),
        ),
        parameter_id=count.id,
        parameter_value=updated_count.value,
    )
    assert edited.status is BuildStatus.SUCCEEDED, edited.diagnostics
    before = adapter.csg_for(initial.snapshot)
    after = adapter.csg_for(edited.snapshot)
    before_max = max(
        len(node.geometry_ids) for node in before.nodes if node.kind == "sketch"
    )
    after_max = max(
        len(node.geometry_ids) for node in after.nodes if node.kind == "sketch"
    )
    assert after_max == before_max + 4


def test_ordinary_pipeline_persists_governing_dual_backend_evidence(
    tmp_path, monkeypatch,
):
    try:
        discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    monkeypatch.setenv("SPEC2CAD_DUAL_BACKEND", "1")
    monkeypatch.setenv("SPEC2CAD_NATIVE_ARTIFACT_ROOT", str(tmp_path.resolve()))
    result = run(
        ROOT / "examples/motor_adapter/sketch.png",
        ROOT / "examples/motor_adapter/motor_datasheet.pdf",
        ROOT / "examples/motor_adapter/requirement.txt",
        backend_override="fixture",
    )
    assert result.latest.backend_evidence["classification"] == "CONSISTENT"
    assert result.latest.backend_evidence["governing"] is True
    assert set(result.latest.backend_evidence["backends"]) == {"cadquery", "freecad"}
    assert result.latest.released is False

    repaired = repair(result, "widen_to_recommended", approved_by="r1h-live-test")
    assert repaired.latest.backend_evidence["classification"] == "CONSISTENT"
    assert repaired.latest.released is True


def test_ordinary_pipeline_blocks_injected_governing_backend_divergence(
    tmp_path, monkeypatch,
):
    from spec2cad import pipeline

    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "A plate 80 mm wide and 50 mm high, made from 8 mm steel, with a 25 mm "
        "centre opening and a 60 mm by 30 mm mounting pattern of four "
        "normal-clearance holes for M5 screws. Add 1.5 mm chamfers to the "
        "external edges. Every hole must sit at least 4 mm from every hole edge.",
        encoding="utf-8",
    )

    def divergent(result, _adapter):
        identity = feature_ir_manifest(result.feature_ir).content_sha256
        result.backend_evidence = {
            "mode": "dual_backend", "feature_ir_sha256": identity,
            "backends": {
                "cadquery": {"status": "succeeded"},
                "freecad": {"status": "succeeded"},
            },
            "classification": "BACKEND_DIVERGENCE", "governing": True,
            "checks": [], "reasons": ["injected measured divergence"],
        }
        return ClassifiedReconciliation(
            feature_ir_sha256=identity,
            classification=ReconciliationClassification.BACKEND_DIVERGENCE,
            governing=True,
            reasons=("injected measured divergence",),
        )

    monkeypatch.setenv("SPEC2CAD_DUAL_BACKEND", "1")
    monkeypatch.setattr(pipeline, "_run_dual_backend_evidence", divergent)
    result = run(requirement=requirement)
    assert all(
        check.status.value == "pass"
        for report in result.latest.measured for check in report.checks
    )
    assert result.latest.released is False
    assert result.latest.backend_evidence["classification"] == "BACKEND_DIVERGENCE"
