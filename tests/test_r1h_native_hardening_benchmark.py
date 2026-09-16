import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_committed_r1h_benchmark_report_is_complete_and_passing():
    report = json.loads(
        (ROOT / "eval/r1h_native_hardening_report.json").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "1.0.0"
    assert report["benchmark"] == "B.R1H"
    assert report["all_passed"] is True
    assert {item["family"] for item in report["families"]} == {
        "interface_plate", "slotted_bracket", "solid_cylinder", "hollow_tube",
    }
    assert all(
        backend["failure_count"] == 0 and backend["repeatable_semantics"]
        for family in report["families"]
        for backend in family["backends"].values()
    )
    assert report["topology_edit"]["after_curves"] == (
        report["topology_edit"]["before_curves"] + 4
    )
    assert {
        value["status"] for value in report["typed_refusals"].values()
    } == {"unsupported"}
