"""The reviewed R1 CadQuery baseline changes only through an explicit update."""

import json

from eval.motor_adapter_reference import REFERENCE, build_reference


def test_motor_adapter_reference_matches_current_pipeline_exactly():
    expected = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert build_reference() == expected


def test_reference_captures_blocked_v1_released_v2_and_step_round_trip():
    reference = build_reference()
    assert [item["release"]["status"] for item in reference["revisions"]] == [
        "blocked", "authorised",
    ]
    assert reference["step_round_trip"]["all_reports_passed"] is True
    assert reference["step_round_trip"]["geometry_matches_in_memory"] is True
    assert all(
        len(item["feature_ir"]["content_sha256"]) == 64
        for item in reference["revisions"]
    )
