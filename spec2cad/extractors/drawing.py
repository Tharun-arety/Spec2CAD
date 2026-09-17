"""Sketch extraction entry point: dispatches to vision or fixture replay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spec2cad.extractors.base import (
    VisionBackend,
    backend_label,
    safe_backend_error,
    select_backend,
)
from spec2cad.extractors.fixtures import FixtureNotFound, load_fixture_evidence
from spec2cad.extractors.model_provider import ModelConnection
from spec2cad.extractors.vision import VisionExtractionError, extract_sketch_with_vision
from spec2cad.schemas.evidence import Evidence


@dataclass(frozen=True)
class SketchExtraction:
    evidence: list[Evidence]
    backend: VisionBackend
    label: str
    fell_back: bool = False
    fallback_reason: Optional[str] = None


def extract_sketch(
    image_path: str | Path,
    backend_override: Optional[str] = None,
    *,
    allow_fallback: bool = True,
    model_connection: ModelConnection | None = None,
) -> SketchExtraction:
    """Extract facts from a sketch using whichever backend is configured.

    If a vision backend is selected but fails at call time (no network, bad key,
    a refusal), we fall back to the recorded fixture rather than aborting the
    demo -- but the result says plainly that it fell back and why. Silently
    substituting a recording for a live call would misrepresent the run.

    Pass allow_fallback=False when measuring a real extractor, so a failure is
    an honest failure rather than a fixture in disguise.
    """
    image_path = Path(image_path)
    backend = select_backend(backend_override, model_connection)

    if backend is VisionBackend.FIXTURE:
        return SketchExtraction(
            evidence=load_fixture_evidence(image_path),
            backend=backend,
            label=backend_label(backend, model_connection),
        )

    try:
        evidence = extract_sketch_with_vision(
            image_path, backend, model_connection,
        )
        return SketchExtraction(
            evidence=evidence,
            backend=backend,
            label=backend_label(backend, model_connection),
        )
    except (VisionExtractionError, Exception) as exc:  # noqa: B014 - report any failure
        if not allow_fallback:
            raise
        try:
            evidence = load_fixture_evidence(image_path)
        except FixtureNotFound:
            raise exc from None
        reason = safe_backend_error(exc)
        return SketchExtraction(
            evidence=evidence,
            backend=VisionBackend.FIXTURE,
            label=(
                f"{backend_label(VisionBackend.FIXTURE)} after "
                f"{backend_label(backend, model_connection)} failed"
            ),
            fell_back=True,
            fallback_reason=reason,
        )
