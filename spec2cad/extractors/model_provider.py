"""Request-scoped configuration for schema-constrained model providers.

Credentials in this module are deliberately immutable, excluded from repr, and
never attached to evidence or run state.  A caller may pass a connection down
one extraction call; the server environment remains the fallback for existing
deployments and CLI use.
"""

from __future__ import annotations

import os
import re
import ipaddress
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit, urlunsplit


class ModelProvider(str, Enum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


_MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"
_DEFAULT_COMPATIBLE_HOSTS = {
    "api.deepseek.com",
    "api.groq.com",
    "api.mistral.ai",
    "api.together.xyz",
    "api.x.ai",
    "openrouter.ai",
}


def allowed_model_hosts() -> tuple[str, ...]:
    """Return exact HTTPS hosts approved for server-side custom model calls."""
    configured = {
        item.strip().lower()
        for item in os.environ.get("SPEC2CAD_ALLOWED_MODEL_HOSTS", "").split(",")
        if item.strip()
    }
    return tuple(sorted(_DEFAULT_COMPATIBLE_HOSTS | configured))


def _normalise_base_url(value: str) -> str:
    if len(value) > 512 or any(ord(char) < 32 for char in value):
        raise ValueError("model base URL is invalid")
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("custom model endpoints must use an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("model base URL cannot contain credentials, a query, or a fragment")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if (
        host == "localhost"
        or host.endswith((".local", ".internal"))
        or (address is not None and not address.is_global)
    ):
        raise ValueError("model endpoint host must be a public provider hostname")
    if host not in allowed_model_hosts():
        raise ValueError(
            f"model endpoint host {host!r} is not approved by this deployment"
        )
    if parsed.port not in {None, 443}:
        raise ValueError("custom model endpoints must use HTTPS port 443")
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or "/v1"
    return urlunsplit(("https", f"{host}{port}", path, "", ""))


@dataclass(frozen=True)
class ModelConnection:
    """One ephemeral caller-owned credential and provider selection."""

    provider: ModelProvider
    api_key: str = field(repr=False)
    model: str
    base_url: str | None = None

    def __post_init__(self) -> None:
        if not self.api_key or len(self.api_key) > 512:
            raise ValueError("model API key must be between 1 and 512 characters")
        if any(ord(char) < 32 for char in self.api_key):
            raise ValueError("model API key contains invalid control characters")
        if not re.fullmatch(_MODEL_PATTERN, self.model):
            raise ValueError("model name contains unsupported characters")
        if self.provider is ModelProvider.OPENAI:
            if self.base_url:
                raise ValueError("OpenAI uses its fixed API endpoint; choose custom for a base URL")
            return
        if not self.base_url:
            raise ValueError("an OpenAI-compatible provider requires a base URL")
        object.__setattr__(self, "base_url", _normalise_base_url(self.base_url))

    @property
    def display_name(self) -> str:
        return "OpenAI" if self.provider is ModelProvider.OPENAI else "OpenAI-compatible"


def openai_client_options(
    connection: ModelConnection | None,
    *,
    default_api_key: str,
    timeout: float,
) -> dict[str, object]:
    """Build SDK options without exposing the credential to logs or state."""
    options: dict[str, object] = {
        "api_key": connection.api_key if connection else default_api_key,
        "timeout": timeout,
        "max_retries": 1,
    }
    if connection and connection.base_url:
        options["base_url"] = connection.base_url
    return options
