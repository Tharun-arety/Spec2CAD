"""The static showcase must present real parts backed by distinct CAD plans."""

import pytest

from scripts.freeze_demo import SCENARIOS, _run_advanced_scenario


@pytest.mark.parametrize(
    ("scenario_id", "operation_type"),
    [
        ("flanged-shaft-coupling", "flanged_coupling"),
        ("sheet-metal-enclosure", "controller_enclosure"),
        ("motor-mount-bracket", "motor_mount_bracket"),
        ("hydraulic-manifold", "hydraulic_manifold"),
        ("blower-transition-duct", "blower_transition_duct"),
    ],
)
def test_benchmark_scenarios_build_distinct_valid_solids(
    scenario_id, operation_type,
):
    scenario = next(item for item in SCENARIOS if item["id"] == scenario_id)

    result = _run_advanced_scenario(scenario)

    assert result.latest.execution.shape.isValid()
    assert len(result.latest.execution.shape.Solids()) == 1
    assert [operation.type for operation in result.latest.program.operations] == [
        operation_type
    ]


def test_showcase_cards_lead_with_product_identity_not_operation_names():
    assert len(SCENARIOS) == 5
    assert [scenario["step"] for scenario in SCENARIOS] == ["01", "02", "03", "04", "05"]
    assert [scenario["inputs"] for scenario in SCENARIOS] == [
        ["text"], ["sketch"], ["text", "sketch"],
        ["sketch", "document"], ["text", "sketch", "document"],
    ]
    assert all(scenario["operation"] for scenario in SCENARIOS)


def test_each_resolvable_blocked_workflow_has_one_approved_revision():
    revisions = {
        scenario["id"]: len(_run_advanced_scenario(scenario).revisions)
        for scenario in SCENARIOS
    }
    assert revisions == {
        "flanged-shaft-coupling": 2,
        "sheet-metal-enclosure": 2,
        "motor-mount-bracket": 2,
        "hydraulic-manifold": 1,
        "blower-transition-duct": 2,
    }


@pytest.mark.parametrize("scenario_id", ["flanged-shaft-coupling", "sheet-metal-enclosure"])
def test_clarification_approval_changes_geometry_and_releases_step(scenario_id):
    scenario = next(item for item in SCENARIOS if item["id"] == scenario_id)
    result = _run_advanced_scenario(scenario)

    assert result.revisions[0].released is False
    assert result.revisions[1].released is True
    assert result.revisions[1].execution.shape.Volume() < result.revisions[0].execution.shape.Volume()
