"""Repeatable, dependency-free pre-deployment profile for the public path.

This is deliberately a small diagnostic harness rather than a load-testing
claim. It measures one process on the current machine, records its environment,
and keeps deterministic geometry separate from HTTP transport overhead.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import platform
import pstats
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def sample_latency(operation: Callable[[], object], repeats: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "count": len(samples),
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
    }


def cold_import() -> dict[str, object]:
    probe = (
        "import json,time; started=time.perf_counter(); import api.main; "
        "print(json.dumps({'seconds':time.perf_counter()-started}))"
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "MODEL_PROVIDER": "stub"},
    )
    wall = time.perf_counter() - started
    child = json.loads(completed.stdout.strip().splitlines()[-1])
    return {
        "module_import_seconds": round(float(child["seconds"]), 4),
        "process_wall_seconds": round(wall, 4),
    }


def bundle_sizes() -> dict[str, object]:
    assets = ROOT / "web" / "dist" / "assets"
    files = []
    if assets.exists():
        files = [
            {"name": path.name, "bytes": path.stat().st_size}
            for path in sorted(assets.iterdir())
            if path.is_file()
        ]
    return {"total_bytes": sum(item["bytes"] for item in files), "files": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build/predeploy-profile.json")
    parser.add_argument("--geometry-repeats", type=int, default=3)
    args = parser.parse_args()

    os.environ.setdefault("MODEL_PROVIDER", "stub")
    startup = cold_import()

    from fastapi.testclient import TestClient

    import api.main as api_main
    from spec2cad.pipeline import run

    client = TestClient(api_main.app)
    client.get("/health").raise_for_status()

    sequential_health = sample_latency(
        lambda: client.get("/health").raise_for_status(), 100,
    )

    concurrent_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(lambda _: client.get("/health"), range(160)))
    concurrent_seconds = time.perf_counter() - concurrent_started

    example = ROOT / "examples/motor_adapter"

    def deterministic_run():
        return run(
            example / "sketch.png",
            example / "motor_datasheet.pdf",
            example / "requirement.txt",
            backend_override="fixture",
            use_reasoning=False,
        )

    geometry = sample_latency(deterministic_run, args.geometry_repeats)
    profiler = cProfile.Profile()
    profiler.enable()
    deterministic_run()
    profiler.disable()
    stats = pstats.Stats(profiler)
    hottest = sorted(
        (
            {
                "function": f"{key[0]}:{key[1]}:{key[2]}",
                "calls": value[1],
                "self_seconds": round(value[2], 6),
                "cumulative_seconds": round(value[3], 6),
            }
            for key, value in stats.stats.items()
        ),
        key=lambda item: item["cumulative_seconds"],
        reverse=True,
    )[:15]

    payload = {
        "scope": "single-process local diagnostic; not a production capacity claim",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor_count": os.cpu_count(),
        },
        "startup": startup,
        "http": {
            "health_sequential": sequential_health,
            "health_concurrent": {
                "workers": 16,
                "requests": len(responses),
                "successes": sum(response.status_code == 200 for response in responses),
                "wall_seconds": round(concurrent_seconds, 4),
                "requests_per_second": round(len(responses) / concurrent_seconds, 2),
            },
        },
        "deterministic_geometry": geometry,
        "profile_hottest": hottest,
        "frontend_bundle": bundle_sizes(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
