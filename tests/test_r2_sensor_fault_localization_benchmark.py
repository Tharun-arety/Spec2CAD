"""B.R2 proves bounded fault localization and release behavior."""

import json
from pathlib import Path

import pytest

from eval.r2_sensor_fault_localization import REPORT, run_benchmark
from spec2cad.backends.freecad_worker import (
    FreeCADWorkerUnavailable,
    discover_freecad_cmd,
)


ROOT = Path(__file__).resolve().parents[1]


def test_b_r2_injected_fault_catalog(tmp_path):
    try:
        discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")

    report = run_benchmark(tmp_path)

    assert report["schema_version"] == "1.0.0"
    assert report["benchmark"] == "B.R2"
    assert report["all_passed"] is True
    cases = {item["fault"]: item for item in report["cases"]}
    assert set(cases) == {
        "compiler", "constraint", "recompute", "topology", "measurement",
        "visual_false_positive", "unavailable_sensor",
    }
    assert cases["compiler"]["origin"] == "intent_compilation"
    assert cases["constraint"]["origin"] == "feature_ir_lowering"
    assert cases["recompute"]["origin"] == "backend_realization"
    assert cases["topology"]["origin"] == "topology"
    assert cases["measurement"]["origin"] == "measurement"
    assert all(
        cases[name]["trace_complete"]
        and cases[name]["release"] == "blocked"
        for name in (
            "compiler", "constraint", "recompute", "topology", "measurement"
        )
    )
    assert cases["visual_false_positive"]["origin"] == "visual_inspection"
    assert cases["visual_false_positive"]["advisory"] is True
    assert cases["visual_false_positive"]["release"] == "authorised"
    assert cases["unavailable_sensor"]["consistency"] == "not_assessed"
    assert cases["unavailable_sensor"]["release"] == "blocked"


def test_committed_b_r2_report_matches_the_versioned_contract():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["schema_version"] == "1.0.0"
    assert report["benchmark"] == "B.R2"
    assert report["all_passed"] is True
