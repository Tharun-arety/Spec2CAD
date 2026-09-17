"""HTTP-boundary checks for the public FastAPI surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.main as main


client = TestClient(main.app)


def test_health_exposes_transport_diagnostics_and_short_public_cache():
    response = client.get("/health", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32
    assert response.headers["Server-Timing"].startswith("app;dur=")
    assert float(response.headers["X-Spec2CAD-Queue-Wait-Ms"]) >= 0
    assert response.headers["Cache-Control"] == (
        "public, max-age=15, stale-while-revalidate=30"
    )
    assert response.headers["Content-Encoding"] == "gzip"
    assert response.json()["public_limits"]["max_concurrent_jobs"] >= 1


def test_public_run_listing_is_disabled_without_admin_secret(monkeypatch):
    monkeypatch.delenv("SPEC2CAD_ADMIN_TOKEN", raising=False)
    response = client.get("/runs")
    assert response.status_code == 404


def test_oversized_instruction_is_rejected_before_model_call():
    response = client.post(
        "/runs", data={"requirement": "x" * (main.limits.max_requirement_chars + 1)}
    )
    assert response.status_code == 413
    assert "character" in response.json()["detail"]


def test_fake_image_is_rejected_before_vision_call():
    response = client.post(
        "/runs", files={"sketch": ("sketch.png", b"not an image", "image/png")}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "uploaded sketch is not a valid image"


def test_exhausted_daily_budget_returns_429_without_calling_provider(monkeypatch):
    class Exhausted:
        def reserve(self, key, units):
            raise ValueError("global_daily_limit")

    monkeypatch.setattr(main, "ai_budget", Exhausted())
    monkeypatch.setattr(main, "reasoning_available", lambda: True)
    response = client.post("/runs", data={"requirement": "make a 10 mm cube"})
    assert response.status_code == 429
    assert "daily AI budget" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) > 0


def test_provider_metadata_without_request_key_is_rejected():
    response = client.post(
        "/runs",
        data={
            "requirement": "make a 10 mm cube",
            "model_provider": "openai",
            "model_name": "gpt-4o",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "model provider settings require an API key"


def test_unapproved_custom_endpoint_is_rejected_without_echoing_secret():
    secret = "caller-secret-key"
    response = client.post(
        "/runs",
        headers={"X-Spec2CAD-Model-API-Key": secret},
        data={
            "requirement": "make a 10 mm cube",
            "model_provider": "openai_compatible",
            "model_name": "test-model",
            "model_base_url": "https://models.invalid/v1",
        },
    )
    assert response.status_code == 400
    assert "not approved" in response.json()["detail"]
    assert secret not in response.text


def test_byok_connection_reaches_pipeline_without_using_server_budget(monkeypatch):
    fake_result = main.run(
        requirement="A plate 60 mm wide and 40 mm high, made from 6 mm aluminium.",
        use_reasoning=False,
    )
    captured = {}

    class ServerBudgetMustNotRun:
        def reserve(self, key, units):
            raise AssertionError("caller-owned credentials must not spend server AI budget")

    def fake_run(*args, **kwargs):
        captured["connection"] = kwargs["model_connection"]
        return fake_result

    monkeypatch.setattr(main, "ai_budget", ServerBudgetMustNotRun())
    monkeypatch.setattr(main, "run", fake_run)
    secret = "caller-secret-key"

    response = client.post(
        "/runs",
        headers={"X-Spec2CAD-Model-API-Key": secret},
        data={
            "requirement": "make a 10 mm cube",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
        },
    )

    assert response.status_code == 200
    assert captured["connection"].model == "gpt-4o-mini"
    assert captured["connection"].api_key == secret
    assert secret not in response.text
