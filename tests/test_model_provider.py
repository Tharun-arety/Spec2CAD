"""Security and validation contracts for request-scoped model connections."""

from __future__ import annotations

import pytest

import spec2cad.pipeline as pipeline
from spec2cad.extractors.model_provider import (
    ModelConnection,
    ModelProvider,
    allowed_model_hosts,
    openai_client_options,
)


def test_openai_connection_keeps_secret_out_of_repr_and_client_metadata():
    connection = ModelConnection(
        provider=ModelProvider.OPENAI,
        api_key="caller-secret-key",
        model="gpt-4o",
    )

    assert "caller-secret-key" not in repr(connection)
    options = openai_client_options(
        connection, default_api_key="server-key", timeout=30,
    )
    assert options["api_key"] == "caller-secret-key"
    assert "base_url" not in options


def test_custom_connection_normalises_an_allowlisted_https_endpoint():
    connection = ModelConnection(
        provider=ModelProvider.OPENAI_COMPATIBLE,
        api_key="caller-secret-key",
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1/",
    )

    assert connection.base_url == "https://openrouter.ai/api/v1"
    assert connection.display_name == "OpenAI-compatible"


@pytest.mark.parametrize("url", [
    "http://openrouter.ai/api/v1",
    "https://localhost/v1",
    "https://user:pass@openrouter.ai/v1",
    "https://openrouter.ai/v1?token=secret",
])
def test_custom_connection_rejects_unsafe_or_unapproved_endpoints(url):
    with pytest.raises(ValueError):
        ModelConnection(
            provider=ModelProvider.OPENAI_COMPATIBLE,
            api_key="caller-secret-key",
            model="test-model",
            base_url=url,
        )


def test_deployment_can_add_an_exact_compatible_host(monkeypatch):
    monkeypatch.setenv("SPEC2CAD_ALLOWED_MODEL_HOSTS", "models.example.com")

    assert "models.example.com" in allowed_model_hosts()
    connection = ModelConnection(
        provider=ModelProvider.OPENAI_COMPATIBLE,
        api_key="caller-secret-key",
        model="private-model",
        base_url="https://models.example.com/v1",
    )
    assert connection.base_url == "https://models.example.com/v1"


def test_conversation_forwards_connection_without_attaching_secret_to_run(monkeypatch):
    original = pipeline.run(
        requirement="A plate 60 mm wide and 40 mm high, made from 6 mm aluminium.",
        use_reasoning=False,
    )
    connection = ModelConnection(
        provider=ModelProvider.OPENAI,
        api_key="caller-secret-key",
        model="gpt-4o-mini",
    )
    captured = {}

    def fake_run(*args, **kwargs):
        captured["connection"] = kwargs["model_connection"]
        return original

    monkeypatch.setattr(pipeline, "run", fake_run)

    updated = pipeline.continue_conversation(
        original,
        "Make the plate wider.",
        model_connection=connection,
    )

    assert captured["connection"] is connection
    assert "caller-secret-key" not in repr(updated)
