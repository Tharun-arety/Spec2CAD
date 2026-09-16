"""B.R1 is executable, versioned and covers every R1 release gate."""

from pathlib import Path

import pytest

from eval.r1_native_foundation import MANIFEST, run_benchmark
from spec2cad.backends.freecad_worker import FreeCADWorkerUnavailable, discover_freecad_cmd


def test_b_r1_cross_backend_fidelity_and_native_editability(tmp_path):
    try:
        discover_freecad_cmd()
    except FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    report = run_benchmark(tmp_path)
    assert report["schema_version"] == "1.0.0"
    assert report["benchmark_case"] == "B.R1.motor_adapter"
    assert MANIFEST.is_file()
    assert report["all_passed"]
    assert report["native_parameter_edit"] == {
        "source_revision": 1,
        "result_revision": 2,
        "parameter_id": "dim_plate_width",
        "value": 45.0,
        "recomputed": True,
        "updated_csg": True,
    }
    assert report["step_round_trip_verified"] is True
