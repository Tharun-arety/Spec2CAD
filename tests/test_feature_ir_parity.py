"""The new Feature IR path preserves established motor behavior exactly."""

from pathlib import Path

import pytest

from spec2cad.cad.compiler import compile_design, parameter_table
from spec2cad.cad.executor import execute
from spec2cad.cad.feature_ir_lowering import lower_feature_ir_to_cad_program
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_content_hash
from spec2cad.pipeline import repair, run
from spec2cad.validation import measure as M
from spec2cad.validation.dimensions import run_dimensions
from spec2cad.validation.gate import evaluate_release
from spec2cad.validation.requirements import run_requirements
from spec2cad.validation.topology import run_topology


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


@pytest.fixture
def revisions():
    v1 = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    v2 = repair(v1, "widen_to_recommended", approved_by="parity-test")
    return v1.latest, v2.latest


def _feature_ir_execution(revision):
    document = compile_feature_ir(revision.intent_graph)
    program = lower_feature_ir_to_cad_program(document)
    return document, program, execute(program, parameter_table(revision.intent))


@pytest.mark.parametrize("index", [0, 1])
def test_lowered_program_is_identical_to_legacy_motor_program(revisions, index):
    revision = revisions[index]
    _, lowered, _ = _feature_ir_execution(revision)
    assert lowered == compile_design(revision.intent_graph)


@pytest.mark.parametrize("index", [0, 1])
def test_brep_dimensions_holes_centres_and_volume_are_identical(revisions, index):
    revision = revisions[index]
    _, _, result = _feature_ir_execution(revision)
    legacy = revision.execution.shape
    actual = result.shape
    assert M.plate_extents(actual) == M.plate_extents(legacy)
    assert [item.key(6) for item in M.circular_features(M.top_face(actual))] == [
        item.key(6) for item in M.circular_features(M.top_face(legacy))
    ]
    assert actual.Volume() == pytest.approx(legacy.Volume(), abs=1e-9)


@pytest.mark.parametrize("index", [0, 1])
def test_requirement_and_release_outcomes_are_identical(revisions, index):
    revision = revisions[index]
    _, _, result = _feature_ir_execution(revision)
    reports = [
        run_topology(result.shape, revision.intent),
        run_dimensions(result.shape, revision.intent),
        run_requirements(result.shape, revision.intent, revision.intent_graph),
    ]
    decision = evaluate_release(revision.intent, reports)
    expected = revision.measured[-1].checks
    actual = reports[-1].checks
    assert [(item.id, item.status, item.measured_value) for item in actual] == [
        (item.id, item.status, item.measured_value) for item in expected
    ]
    assert decision.status == revision.decision.status


def test_v1_and_v2_have_distinct_stable_feature_ir_hashes(revisions):
    hashes = [
        feature_ir_content_hash(compile_feature_ir(revision.intent_graph))
        for revision in revisions
    ]
    assert hashes[0] != hashes[1]
    assert hashes == [
        feature_ir_content_hash(compile_feature_ir(revision.intent_graph))
        for revision in revisions
    ]

