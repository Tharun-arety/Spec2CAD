"""Recorded-fixture replay for the no-API-key path.

This exists so the whole pipeline -- fusion, conflict detection, CAD generation,
measured validation, repair -- is demonstrable and testable without a vision
API key. It replays evidence that was recorded from the sketch alongside the
sketch itself.

It is deliberately conspicuous about what it is:

  * every item is stamped extraction_method=RECORDED_FIXTURE
  * Evidence.is_fixture is therefore True
  * eval/metrics.py refuses to count such items toward extraction accuracy
  * the UI shows the method on every row

Replaying a recording proves nothing about extraction, and the system should
never let that be mistaken for a measured capability.
"""

from __future__ import annotations

import json
from pathlib import Path

from spec2cad.fusion.source_policy import authority_for
from spec2cad.schemas.evidence import (
    Evidence,
    EvidenceKind,
    ExtractionMethod,
    SemanticTarget,
    SourceModality,
    SourceRef,
)


class FixtureNotFound(FileNotFoundError):
    """Raised when no recorded fixture accompanies the sketch."""


def fixture_path_for(image_path: str | Path) -> Path:
    """The fixture that accompanies a sketch: sketch.png -> sketch.fixture.json."""
    image_path = Path(image_path)
    return image_path.with_suffix("").with_suffix(".fixture.json") \
        if image_path.suffix else image_path


def load_fixture_evidence(image_path: str | Path) -> list[Evidence]:
    """Replay recorded evidence for a sketch."""
    image_path = Path(image_path)
    fixture = image_path.parent / f"{image_path.stem}.fixture.json"
    if not fixture.exists():
        raise FixtureNotFound(
            f"no recorded fixture at {fixture}. Configure OPENAI_API_KEY or "
            f"ANTHROPIC_API_KEY to extract this sketch for real, or generate the "
            f"fixture with examples/motor_adapter/generate_inputs.py"
        )

    data = json.loads(fixture.read_text(encoding="utf-8"))
    out: list[Evidence] = []

    for item in data.get("items", []):
        target = SemanticTarget(item["target"])
        kind = EvidenceKind(item["kind"])
        explicit = bool(item.get("is_explicit_annotation", False))
        region = item.get("region")

        out.append(
            Evidence(
                id=f"ev_sketch_{target.value}",
                entity="adapter_plate",
                kind=kind,
                target=target,
                value=item["value"],
                unit=item.get("unit"),
                source=SourceRef(
                    file=image_path.name,
                    modality=SourceModality.SKETCH,
                    region=tuple(region) if region else None,
                    detail="replayed from recorded fixture",
                ),
                extraction_method=ExtractionMethod.RECORDED_FIXTURE,
                confidence=float(item.get("confidence", 0.5)),
                authority=authority_for(SourceModality.SKETCH, target, explicit),
                is_explicit_annotation=explicit,
                raw_text=item.get("raw_text"),
            )
        )
    return out
