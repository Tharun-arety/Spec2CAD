"""Genuine multimodal sketch extraction via OpenAI or Anthropic.

The model returns structured facts, never code and never a CAD program. Its
output is validated against SKETCH_JSON_SCHEMA and then against the Evidence
model; anything that does not fit is rejected with the offending payload
reported, rather than being coerced into something that looks plausible.

Authority is NOT taken from the model. The model may say how confident it is
that it read the drawing correctly -- that is `confidence` -- but whether a
sketch is entitled to define a given parameter is a policy decision made in
fusion/source_policy.py. Letting the model assert its own authority would let a
confident misreading outrank a datasheet.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from spec2cad.extractors.base import (
    SKETCH_JSON_SCHEMA,
    SKETCH_PROMPT,
    VisionBackend,
    anthropic_model,
    load_env,
    openai_api_key,
    openai_model,
    model_max_output_tokens,
    model_timeout_seconds,
)
from spec2cad.public_guardrails import current_safety_identifier
from spec2cad.fusion.source_policy import authority_for
from spec2cad.schemas.evidence import (
    Evidence,
    EvidenceKind,
    ExtractionMethod,
    SemanticTarget,
    SourceModality,
    SourceRef,
)


class VisionExtractionError(RuntimeError):
    """Raised when a vision backend returns something unusable."""


def _encode_image(path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return base64.b64encode(path.read_bytes()).decode("ascii"), mime


def _parse_payload(raw: str) -> list[dict[str, Any]]:
    """Parse and shape-check the model's JSON response."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VisionExtractionError(
            f"vision backend did not return valid JSON: {exc}; got {raw[:300]!r}"
        ) from exc

    if not isinstance(payload, dict) or "facts" not in payload:
        raise VisionExtractionError(
            f"vision response missing 'facts' key; got keys {list(payload)[:8]}"
        )
    facts = payload["facts"]
    if not isinstance(facts, list):
        raise VisionExtractionError(f"'facts' must be a list, got {type(facts).__name__}")
    return facts


def _to_evidence(facts: list[dict[str, Any]], image_path: Path, model_name: str) -> list[Evidence]:
    """Validate model facts into Evidence, discarding anything out of contract."""
    out: list[Evidence] = []
    for index, fact in enumerate(facts):
        try:
            target = SemanticTarget(fact["target"])
            kind = EvidenceKind(fact["kind"])
        except (KeyError, ValueError) as exc:
            raise VisionExtractionError(
                f"fact {index} outside the agreed vocabulary: {fact!r} ({exc})"
            ) from exc

        explicit = bool(fact.get("is_explicit_annotation", False))
        region = fact.get("region")
        if region is not None and len(region) != 4:
            region = None

        out.append(
            Evidence(
                id=f"ev_sketch_{target.value}",
                entity="adapter_plate",
                kind=kind,
                target=target,
                value=fact["value"],
                unit=fact.get("unit"),
                source=SourceRef(
                    file=image_path.name,
                    modality=SourceModality.SKETCH,
                    region=tuple(region) if region else None,
                    detail=f"read by {model_name}",
                ),
                extraction_method=ExtractionMethod.VISION_MODEL,
                confidence=float(fact.get("confidence", 0.5)),
                # policy decides entitlement; the model does not
                authority=authority_for(SourceModality.SKETCH, target, explicit),
                is_explicit_annotation=explicit,
                raw_text=fact.get("raw_text"),
            )
        )
    return out


def _extract_openai(image_path: Path) -> list[Evidence]:
    from openai import OpenAI

    load_env()
    client = OpenAI(
        api_key=openai_api_key(),
        timeout=model_timeout_seconds(), max_retries=1,
    )
    b64, mime = _encode_image(image_path)
    model = openai_model()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SKETCH_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "sketch_facts",
                "strict": True,
                "schema": SKETCH_JSON_SCHEMA,
            },
        },
        max_tokens=model_max_output_tokens(),
        user=current_safety_identifier(),
        extra_headers={"X-Client-Request-Id": str(uuid.uuid4())},
    )
    content = response.choices[0].message.content or ""
    return _to_evidence(_parse_payload(content), image_path, model)


def _extract_anthropic(image_path: Path) -> list[Evidence]:
    import anthropic

    load_env()
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=model_timeout_seconds(), max_retries=1,
    )
    b64, mime = _encode_image(image_path)
    model = anthropic_model()

    # A tool with the schema as its input is how we get guaranteed-shape JSON
    # out of the Anthropic API.
    response = client.messages.create(
        model=model,
        max_tokens=min(2000, model_max_output_tokens()),
        tools=[{
            "name": "report_sketch_facts",
            "description": "Report the engineering facts visible on the sketch.",
            "input_schema": SKETCH_JSON_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "report_sketch_facts"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": SKETCH_PROMPT},
            ],
        }],
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return _to_evidence(
                _parse_payload(json.dumps(block.input)), image_path, model
            )
    raise VisionExtractionError(
        "anthropic response contained no tool_use block; "
        f"stop_reason={getattr(response, 'stop_reason', None)}"
    )


def extract_sketch_with_vision(
    image_path: str | Path, backend: VisionBackend
) -> list[Evidence]:
    """Run genuine multimodal extraction against the sketch."""
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"sketch not found: {image_path}")

    if backend is VisionBackend.OPENAI:
        return _extract_openai(image_path)
    if backend is VisionBackend.ANTHROPIC:
        return _extract_anthropic(image_path)
    raise ValueError(f"{backend} is not a vision backend")
