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

Keys are read from the environment or a .env file at the project root.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_LOADED = False


def load_env() -> None:
    """Load .env once, without overriding variables already in the environment."""
    global _ENV_LOADED
    if not _ENV_LOADED:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        _ENV_LOADED = True


class VisionBackend(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    FIXTURE = "fixture"


DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


def openai_model() -> str:
    load_env()
    return os.environ.get("SPEC2CAD_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


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

    if requested != "auto":
        try:
            backend = VisionBackend(requested)
        except ValueError:
            raise ValueError(
                f"unknown SPEC2CAD_VISION_BACKEND {requested!r}; "
                f"expected one of {[b.value for b in VisionBackend]}"
            ) from None
        if backend is VisionBackend.OPENAI and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("SPEC2CAD_VISION_BACKEND=openai but OPENAI_API_KEY is not set")
        if backend is VisionBackend.ANTHROPIC and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "SPEC2CAD_VISION_BACKEND=anthropic but ANTHROPIC_API_KEY is not set"
            )
        return backend

    if os.environ.get("OPENAI_API_KEY"):
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
