"""Extractor backend selection and the shared contract for sketch extraction.

Both paths are first-class:

  * A vision backend (OpenAI or Anthropic) performs genuine multimodal
    extraction when an API key is configured.
  * A recorded fixture replays a previous extraction when no key is available,
    so the whole pipeline is demonstrable offline.

The difference is never hidden. Every item carries its `extraction_method`, the
UI shows it per row, and evaluation keeps the two apart: fixture-sourced
evidence is structurally excluded from any reported extraction-accuracy number
(see eval/metrics.py), because replaying a recording measures nothing about
extraction.

Keys are read from the process environment, Render's
``/etc/secrets/OPENAI_API_KEY`` secret file, ``.env.local``, or ``.env`` at the
project root.  They are never read by the browser application.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENAI_SECRET_FILE = Path("/etc/secrets/OPENAI_API_KEY")
_ENV_LOADED = False
_FILE_MANAGED_VALUES: dict[str, str] = {}


def load_env() -> None:
    """Load local server configuration and safely notice file edits.

    Real process variables have highest priority.  ``.env.local`` is loaded
    before ``.env`` so a developer's untracked local settings win over shared
    defaults. Values that came from the process environment are never
    overwritten. Values previously loaded from a file may be refreshed when
    that file changes, so updating ``.env.local`` does not require a restart.
    """
    global _ENV_LOADED
    shared = {
        key: str(value)
        for key, value in dotenv_values(PROJECT_ROOT / ".env").items()
        if value is not None
    }
    local = {
        key: str(value)
        for key, value in dotenv_values(PROJECT_ROOT / ".env.local").items()
        if value is not None
    }
    configured = {**shared, **local}

    # Remove a file-managed setting if it disappeared from both files. A value
    # changed independently in the process is preserved as an explicit override.
    for key, previous in list(_FILE_MANAGED_VALUES.items()):
        if key not in configured:
            if os.environ.get(key) == previous:
                os.environ.pop(key, None)
            _FILE_MANAGED_VALUES.pop(key, None)

    for key, value in configured.items():
        previous = _FILE_MANAGED_VALUES.get(key)
        if key not in os.environ or (previous is not None and os.environ[key] == previous):
            os.environ[key] = value
            _FILE_MANAGED_VALUES[key] = value
        else:
            # The process supplied or changed this value; it has highest priority.
            _FILE_MANAGED_VALUES.pop(key, None)
    _ENV_LOADED = True


def safe_backend_error(exc: Exception) -> str:
    """Return a useful public error without echoing credentials or payloads."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if status == 401 or name == "AuthenticationError":
        return f"{name}: authentication failed; check the server-side API key"
    if status == 429 or name == "RateLimitError":
        return f"{name}: provider rate limit or quota was reached"
    if name in {"APIConnectionError", "ConnectError", "TimeoutException"}:
        return f"{name}: could not reach the model provider"
    return f"{name}: model backend request failed"


class VisionBackend(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    FIXTURE = "fixture"


DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


def openai_model() -> str:
    load_env()
    return os.environ.get("SPEC2CAD_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def reasoning_model() -> str:
    """Text-reasoning model; defaults to the configured OpenAI vision model."""
    load_env()
    return os.environ.get("SPEC2CAD_REASONING_MODEL", openai_model())


def openai_api_key() -> str | None:
    """Return the server-side key without requiring a particular secret transport.

    Process and dotenv values take precedence. Render secret files are read from
    ``/etc/secrets/OPENAI_API_KEY`` by default; tests and other hosts can
    override that location with ``SPEC2CAD_OPENAI_API_KEY_FILE``.
    """
    load_env()
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if value:
        return value

    secret_path = Path(
        os.environ.get("SPEC2CAD_OPENAI_API_KEY_FILE", str(DEFAULT_OPENAI_SECRET_FILE))
    )
    try:
        value = secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def reasoning_available() -> bool:
    """Whether server-side OpenAI reasoning can be attempted."""
    return bool(openai_api_key())


def model_max_output_tokens() -> int:
    """Hard cap every public structured extraction response."""
    load_env()
    try:
        value = int(os.environ.get("SPEC2CAD_MODEL_MAX_OUTPUT_TOKENS", "3000"))
    except ValueError as exc:
        raise ValueError("SPEC2CAD_MODEL_MAX_OUTPUT_TOKENS must be an integer") from exc
    return max(256, min(value, 8000))


def model_timeout_seconds() -> float:
    load_env()
    try:
        value = float(os.environ.get("SPEC2CAD_MODEL_TIMEOUT_SECONDS", "35"))
    except ValueError as exc:
        raise ValueError("SPEC2CAD_MODEL_TIMEOUT_SECONDS must be numeric") from exc
    return max(5.0, min(value, 120.0))


def anthropic_model() -> str:
    load_env()
    return os.environ.get("SPEC2CAD_ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)


def select_backend(override: Optional[str] = None) -> VisionBackend:
    """Choose the sketch-extraction backend.

    Order: explicit override -> SPEC2CAD_VISION_BACKEND -> whichever API key is
    configured -> fixture replay. Selecting the fixture is a normal outcome, not
    an error, but it is always reported so the caller can label the run.
    """
    load_env()
    requested = (override or os.environ.get("SPEC2CAD_VISION_BACKEND", "auto")).lower()

    configured_openai_key = openai_api_key()
    if requested != "auto":
        try:
            backend = VisionBackend(requested)
        except ValueError:
            raise ValueError(
                f"unknown SPEC2CAD_VISION_BACKEND {requested!r}; "
                f"expected one of {[b.value for b in VisionBackend]}"
            ) from None
        if backend is VisionBackend.OPENAI and not configured_openai_key:
            raise RuntimeError("SPEC2CAD_VISION_BACKEND=openai but OPENAI_API_KEY is not set")
        if backend is VisionBackend.ANTHROPIC and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "SPEC2CAD_VISION_BACKEND=anthropic but ANTHROPIC_API_KEY is not set"
            )
        return backend

    if configured_openai_key:
        return VisionBackend.OPENAI
    if os.environ.get("ANTHROPIC_API_KEY"):
        return VisionBackend.ANTHROPIC
    return VisionBackend.FIXTURE


def backend_label(backend: VisionBackend) -> str:
    """Human-readable description recorded on the run and shown in the UI."""
    if backend is VisionBackend.OPENAI:
        return f"openai vision ({openai_model()})"
    if backend is VisionBackend.ANTHROPIC:
        return f"anthropic vision ({anthropic_model()})"
    return "recorded fixture (no vision API key configured)"


# --------------------------------------------------------------------------
# The contract the vision model must satisfy.
# --------------------------------------------------------------------------

# Targets a sketch can legitimately speak to. The model is not permitted to
# report interface facts it cannot know from an undimensioned drawing.
SKETCH_TARGETS = [
    "plate_width",
    "plate_height",
    "mounting_hole_count",
    "orientation_note",
]

SKETCH_KINDS = ["linear_dimension", "count", "note"]

SKETCH_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "target", "kind", "value", "unit",
                    "confidence", "is_explicit_annotation", "raw_text",
                ],
                "properties": {
                    "target": {"type": "string", "enum": SKETCH_TARGETS},
                    "kind": {"type": "string", "enum": SKETCH_KINDS},
                    "value": {
                        "type": ["number", "string"],
                        "description": "numeric for dimensions and counts, string for notes",
                    },
                    "unit": {
                        "type": ["string", "null"],
                        "description": "'mm' for dimensions, null otherwise",
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_explicit_annotation": {
                        "type": "boolean",
                        "description": (
                            "true when the value is WRITTEN on the drawing; "
                            "false when estimated from the geometry"
                        ),
                    },
                    "raw_text": {
                        "type": "string",
                        "description": "the text as it appears on the drawing",
                    },
                },
            },
        }
    },
}

SKETCH_PROMPT = """You are reading an engineering sketch of a machined plate.

Report ONLY what the drawing actually shows. Specifically:

- Report a dimension only if a number is written on the drawing. Set
  is_explicit_annotation=true for those. Never scale a value off the geometry
  and present it as a dimension.
- Determine which written dimension is the WIDTH (horizontal extent) and which
  is the HEIGHT (vertical extent) from the dimension lines they belong to.
- Count the small mounting holes. Do not count the large central opening as a
  mounting hole.
- If an orientation note is present, report its text verbatim.
- Do NOT report the mounting hole spacing or hole diameters. An undimensioned
  sketch does not establish them, and they come from the motor datasheet.
- Units on this drawing are millimetres.

Return only the facts you can support from the image."""
