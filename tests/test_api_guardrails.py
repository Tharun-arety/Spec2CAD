"""HTTP-boundary checks for the public FastAPI surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.main as main


client = TestClient(main.app)


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
