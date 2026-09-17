"""Deterministic abuse, cost, and resource-boundary tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from spec2cad.public_guardrails import (
    BoundedRunCache,
    DailyAIBudget,
    PublicGuardrailMiddleware,
    PublicLimits,
)
from spec2cad.schemas.cad_ir import BoxOp, CADProgram, NumberLiteral, lit
from spec2cad.schemas.evidence import EvidenceSet
from spec2cad.store import Store


def _guarded_app(limits: PublicLimits) -> TestClient:
    app = FastAPI()
    app.add_middleware(PublicGuardrailMiddleware, limits=limits)

    @app.post("/runs")
    def expensive():
        return {"ok": True}

    return TestClient(app)


def test_request_size_and_sliding_rate_limits_return_public_http_errors():
    limits = PublicLimits(requests_per_minute=2, max_request_bytes=20)
    client = _guarded_app(limits)

    assert client.post("/runs", content=b"1").status_code == 200
    assert client.post("/runs", content=b"2").status_code == 200
    limited = client.post("/runs", content=b"3")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1

    oversized = _guarded_app(limits).post("/runs", content=b"x" * 21)
    assert oversized.status_code == 413


def test_daily_budget_is_atomic_across_concurrent_clients(tmp_path):
    store = Store(tmp_path / "usage.db")
    budget = DailyAIBudget(store, client_limit=3, global_limit=5)

    def reserve_once():
        try:
            budget.reserve("same-hashed-client", 1)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(lambda _: reserve_once(), range(8)))
    assert sum(admitted) == 3

    budget.reserve("other-hashed-client", 2)
    with pytest.raises(ValueError, match="global_daily_limit"):
        budget.reserve("third-hashed-client", 1)


def test_brep_cache_has_a_hard_lru_bound():
    cache = BoundedRunCache(max_entries=2)
    cache["a"] = object()
    cache["b"] = object()
    assert cache.get("a") is not None
    cache["c"] = object()
    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None


def test_cad_ir_rejects_nonfinite_values_and_operation_floods():
    with pytest.raises(ValidationError):
        NumberLiteral(value=float("nan"))
    operation = BoxOp(id="body", width=lit(1), height=lit(1), depth=lit(1))
    with pytest.raises(ValidationError):
        CADProgram(part_name="flood", operations=[operation] * 65)


def test_public_run_ids_use_full_unpredictable_uuid(tmp_path):
    store = Store(tmp_path / "runs.db")
    run_id = store.create_run(
        tmp_path, EvidenceSet(items=[]), "test backend"
    )
    assert len(run_id) == 32
    int(run_id, 16)


def test_expensive_jobs_fail_fast_with_observable_queue_wait():
    entered = Event()
    release = Event()
    app = FastAPI()
    app.add_middleware(
        PublicGuardrailMiddleware,
        limits=PublicLimits(
            requests_per_minute=10,
            max_concurrent_jobs=1,
            job_queue_timeout_ms=20,
        ),
    )

    @app.post("/runs")
    def expensive():
        entered.set()
        release.wait(timeout=2)
        return {"ok": True}

    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/runs")
        assert entered.wait(timeout=1)
        rejected = client.post("/runs")
        release.set()
        accepted = first.result(timeout=2)

    assert accepted.status_code == 200
    assert rejected.status_code == 503
    assert rejected.headers["Retry-After"] == "2"
    assert float(rejected.headers["X-Spec2CAD-Queue-Wait-Ms"]) >= 15
    assert len(rejected.headers["X-Request-ID"]) == 32
