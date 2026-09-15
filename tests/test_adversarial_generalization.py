"""Acceptance tests for the adversarial generalization evaluation itself."""

from __future__ import annotations

import inspect
import json

import pytest

import spec2cad.cad.compiler as planner
from eval.adversarial_generalization import (
    Level,
    Metric,
    run_suite,
    write_reports,
)


@pytest.fixture(scope="module")
def adversarial_report():
    return run_suite()


def test_adversarial_suite_passes_without_changing_the_planner(adversarial_report):
    failures = [outcome for outcome in adversarial_report.outcomes if not outcome.passed]
    assert failures == []
    assert adversarial_report.all_passed


def test_metrics_are_separate_and_each_is_exercised(adversarial_report):
    summaries = {summary.metric: summary for summary in adversarial_report.summaries}
    assert set(summaries) == {metric.value for metric in Metric}
    assert all(summary.total > 0 for summary in summaries.values())
    assert all(summary.passed == summary.total for summary in summaries.values())


def test_all_requested_levels_and_adversaries_are_present(adversarial_report):
    assert {outcome.level for outcome in adversarial_report.outcomes} == {
        level.value for level in Level
    }
    cases = {outcome.case for outcome in adversarial_report.outcomes}
    assert {
        "motor_adapter",
        "slotted_mounting_bracket",
        "changed_dimensions",
        "missing_dimensions",
        "contradictory_sources",
        "inch_mm_normalization",
        "removed_features",
        "reordered_features",
        "unsatisfiable_requirement",
        "unseen_rectangular_flange",
        "wrong_executor_dimension",
        "symbolic_measurement_disagreement",
        "persisted_graph_replay",
    } <= cases


def test_unseen_flange_is_not_named_in_the_graph_feature_planner(adversarial_report):
    source = inspect.getsource(planner._compile_graph).lower()
    assert "rectangular_flange" not in source
    assert "mounting_bracket" not in source
    assert "motor_adapter" not in source
    assert "part_name ==" not in source

    independence = next(
        outcome for outcome in adversarial_report.outcomes
        if outcome.case == "unseen_rectangular_flange"
        and outcome.assertion == "renaming the part leaves every operation unchanged"
    )
    assert independence.passed


def test_faults_and_refusals_have_the_right_failure_class(adversarial_report):
    by_case_assertion = {
        (outcome.case, outcome.assertion): outcome
        for outcome in adversarial_report.outcomes
    }
    wrong_dimension = by_case_assertion[
        ("wrong_executor_dimension", "B-Rep validation catches executor width corruption")
    ]
    assert wrong_dimension.actual == ("fail", 69.0, "execution")

    inconsistency = by_case_assertion[
        ("symbolic_measurement_disagreement",
         "symbolic disagreement is a pipeline inconsistency")
    ]
    assert inconsistency.actual == ("fail", "execution", "pass")
    assert adversarial_report.correct_refusals == 4


def test_reports_are_human_and_machine_readable(adversarial_report, tmp_path):
    markdown = tmp_path / "report.md"
    machine = tmp_path / "report.json"
    write_reports(adversarial_report, markdown, machine)

    text = markdown.read_text(encoding="utf-8")
    payload = json.loads(machine.read_text(encoding="utf-8"))
    assert "Metrics by pipeline stage" in text
    assert "unseen_rectangular_flange" in text
    assert payload["all_passed"] is True
    assert payload["correct_refusals"] == 4
    assert {metric["metric"] for metric in payload["metrics"]} == {
        metric.value for metric in Metric
    }
