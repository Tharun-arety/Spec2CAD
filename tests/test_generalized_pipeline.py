"""The same graph/compiler/predicate pipeline must handle an unseen feature set."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec2cad.cad.compiler import compile_design
from spec2cad.cad.executor import export_step
from spec2cad.pipeline import run, verify_exported_step
from spec2cad.schemas.cad_ir import (
    BoxOp,
    FilletOp,
    LinearSlotPatternOp,
    RectangularHolePatternOp,
)
from spec2cad.schemas.intent_graph import EdgeKind, FeatureNode, FeatureType
from spec2cad.schemas.requirement_ir import MinimumDistancePredicate
from spec2cad.validation.predicate_compiler import compile_requirement_predicates
from spec2cad.store import Store

EXAMPLE = Path("examples/mounting_bracket")


@pytest.fixture(scope="module")
def bracket():
    return run(requirement=EXAMPLE / "requirement.txt")


def test_second_part_family_runs_end_to_end(bracket):
    rev = bracket.latest
    assert rev.intent.part.name == "mounting_bracket"
    assert rev.intent_graph is not None
    assert rev.build_error is None
    assert rev.execution.shape.isValid()
    assert rev.released is True


def test_feature_plan_is_synthesized_from_graph_not_part_name(bracket):
    graph = bracket.latest.intent_graph
    program = compile_design(graph)

    assert [type(op) for op in program.operations] == [
        BoxOp,
        RectangularHolePatternOp,
        LinearSlotPatternOp,
        FilletOp,
    ]
    assert [op.id for op in program.operations] == [
        "base_plate", "mounting_holes", "base_slots", "external_fillets",
    ]

    # Renaming the part cannot change its feature plan; there is no
    # `if part == bracket` route hidden in the compiler.
    renamed_nodes = [
        node.model_copy(update={"name": "unseen_part", "label": "unseen_part"})
        if getattr(getattr(node, "kind", None), "value", None) == "part" else node
        for node in graph.nodes
    ]
    renamed = graph.model_copy(update={"nodes": renamed_nodes})
    renamed_program = compile_design(renamed)
    assert [op.model_dump(exclude={"id"}) for op in renamed_program.operations] == [
        op.model_dump(exclude={"id"}) for op in program.operations
    ]
    # The temporary flat compatibility projection remains equivalent while
    # downstream consumers migrate to the graph.
    assert compile_design(bracket.latest.intent) == program


def test_slots_and_fillets_are_measured_from_brep(bracket):
    checks = {check.id: check for check in bracket.latest.all_checks()}
    assert checks["dim_slot_count"].status.value == "pass"
    assert checks["dim_slot_width"].measured_value == pytest.approx(8.0, abs=1e-6)
    assert checks["dim_slot_length"].measured_value == pytest.approx(20.0, abs=1e-6)
    assert checks["dim_slot_spacing_x"].measured_value == pytest.approx(50.0, abs=1e-6)
    assert checks["dim_external_fillet"].measured_value == 4
    assert checks["top_material_integrity"].status.value == "pass"


def test_requirement_relation_compiles_to_geometric_predicate(bracket):
    graph = bracket.latest.intent_graph
    program = compile_requirement_predicates(graph)
    assert len(program.predicates) == 1
    predicate = program.predicates[0]
    assert isinstance(predicate, MinimumDistancePredicate)
    assert predicate.subject.feature_id == "mounting_holes"
    assert predicate.target.part_id == "part"
    assert predicate.threshold == pytest.approx(3.0)

    governed = graph.out_edges("c_min_hole_edge_clearance", EdgeKind.CONSTRAINS)
    assert [edge.target for edge in governed] == [predicate.subject.feature_id]
    feature = graph.node(predicate.subject.feature_id)
    assert isinstance(feature, FeatureNode)
    assert feature.feature_type is FeatureType.HOLE_PATTERN


def test_requirement_executor_reports_compiled_predicate(bracket):
    check = bracket.latest.measured[-1].get("req_edge_clearance")
    assert check.status.value == "pass"
    assert check.measured_value == pytest.approx(7.5, abs=1e-6)
    assert "compiled minimum_distance predicate" in check.message


def test_second_family_step_round_trip_revalidates(bracket, tmp_path):
    rev = bracket.latest
    step = export_step(rev.execution, tmp_path / "mounting_bracket.step")
    reports = verify_exported_step(step, rev.intent, rev.intent_graph)
    assert all(report.passed for report in reports), [
        check.message for report in reports for check in report.failures
    ]


def test_intent_graph_is_persisted_as_the_rebuild_source(bracket, tmp_path):
    store = Store(tmp_path / "spec2cad.db")
    run_id = store.create_run(
        EXAMPLE,
        bracket.evidence,
        bracket.sketch_backend,
    )
    rev = bracket.latest
    store.save_revision(run_id, rev.intent, {
        "intent_graph": rev.intent_graph.model_dump(mode="json"),
    })

    restored = store.get_intent_graph(run_id, rev.revision)
    assert restored == rev.intent_graph
    assert compile_design(restored) == rev.program
