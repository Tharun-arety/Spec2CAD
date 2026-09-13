"""Requirement-text extraction.

Deterministic rule parsing over the free-text requirement. Two things are worth
noting about the design:

1. Unit normalisation keeps the original literal. A value converted from inches
   reports value=5.0 unit='mm' AND original_value='0.197 in', so the evidence
   table can show what the document actually said next to what we made of it.

2. "M3 normal-clearance" does not directly yield a diameter. It yields a thread
   spec and a fit class, which are then looked up in ISO 273. The resulting
   diameter is emitted as separate evidence with extraction_method=
   KNOWLEDGE_TABLE and the clause cited in source.detail, so the 3.4 in the
   evidence table is attributable to a standard rather than to a guess.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from spec2cad.knowledge.fastener_tables import UnknownThread, clearance_hole, fit_from_text
from spec2cad.fusion.source_policy import authority_for
from spec2cad.schemas.evidence import (
    Evidence,
    EvidenceKind,
    ExtractionMethod,
    SemanticTarget,
    SourceModality,
    SourceRef,
)

_NUM = r"\d+(?:\.\d+)?"

MM_PER_INCH = 25.4

MATERIALS = {
    "aluminium": "Aluminium",
    "aluminum": "Aluminium",
    "steel": "Steel",
    "stainless": "Stainless steel",
    "brass": "Brass",
    "titanium": "Titanium",
}


def _to_mm(value: float, unit: str) -> tuple[float, str]:
    """Normalise a length to mm, returning (value_mm, canonical_unit)."""
    u = unit.lower().strip().rstrip(".")
    if u in ("mm", "millimetre", "millimeter", "millimetres", "millimeters"):
        return value, "mm"
    if u in ("cm", "centimetre", "centimeter"):
        return value * 10.0, "mm"
    if u in ("in", "inch", "inches", '"'):
        return round(value * MM_PER_INCH, 4), "mm"
    raise ValueError(f"unrecognised unit {unit!r}")


def _mk(
    ev_id: str,
    target: SemanticTarget,
    kind: EvidenceKind,
    value,
    unit: Optional[str],
    *,
    source_name: str,
    confidence: float,
    explicit: bool,
    raw: str,
    original: Optional[str] = None,
    method: ExtractionMethod = ExtractionMethod.RULE_PARSER,
    detail: Optional[str] = None,
) -> Evidence:
    modality = (
        SourceModality.ENGINEERING_RULE
        if method is ExtractionMethod.KNOWLEDGE_TABLE
        else SourceModality.REQUIREMENT_TEXT
    )
    return Evidence(
        id=ev_id,
        entity="adapter_plate",
        kind=kind,
        target=target,
        value=value,
        unit=unit,
        source=SourceRef(file=source_name, modality=modality, detail=detail),
        extraction_method=method,
        confidence=confidence,
        authority=authority_for(modality, target, explicit),
        is_explicit_annotation=explicit,
        raw_text=raw,
        original_value=original,
    )


def extract_requirement(
    text_or_path: str | Path, source_name: str = "requirement.txt"
) -> list[Evidence]:
    """Parse the requirement text into evidence.

    Accepts either the text itself or a path to a file containing it.
    """
    if isinstance(text_or_path, Path) or (
        isinstance(text_or_path, str) and Path(text_or_path).suffix == ".txt"
    ):
        path = Path(text_or_path)
        if path.exists():
            source_name = path.name
            text = path.read_text(encoding="utf-8")
        else:
            text = str(text_or_path)
    else:
        text = str(text_or_path)

    out: list[Evidence] = []

    # --- thickness + material: "from 5 mm aluminium" -----------------------
    m = re.search(
        rf"({_NUM})\s*(mm|cm|in|inch|inches|millimet(?:re|er)s?)\s+"
        rf"(aluminium|aluminum|steel|stainless|brass|titanium)",
        text, re.IGNORECASE,
    )
    if m:
        raw_val, raw_unit, raw_mat = m.group(1), m.group(2), m.group(3)
        value_mm, unit = _to_mm(float(raw_val), raw_unit)
        original = None if unit == raw_unit.lower() else f"{raw_val} {raw_unit}"
        out.append(_mk(
            "ev_txt_plate_thickness", SemanticTarget.PLATE_THICKNESS,
            EvidenceKind.LINEAR_DIMENSION, value_mm, unit,
            source_name=source_name, confidence=0.99, explicit=True,
            raw=m.group(0), original=original,
        ))
        out.append(_mk(
            "ev_txt_material", SemanticTarget.MATERIAL, EvidenceKind.MATERIAL_SPEC,
            MATERIALS[raw_mat.lower()], None,
            source_name=source_name, confidence=0.99, explicit=True, raw=m.group(0),
        ))

    # --- thread + fit: "normal-clearance holes for M3 screws" --------------
    m = re.search(r"\bM(\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
    if m:
        thread = f"M{m.group(1)}"
        # look at the clause around the callout so "normal-clearance" is in scope
        window = text[max(0, m.start() - 90): m.end() + 40]
        fit = fit_from_text(window)
        out.append(_mk(
            "ev_txt_thread", SemanticTarget.MOUNTING_THREAD_SPEC,
            EvidenceKind.THREAD_CALLOUT, thread, None,
            # the datasheet also states the screw size and owns the interface,
            # so the policy ranks this as supporting rather than definitive
            source_name=source_name, confidence=0.98, explicit=True,
            raw=window.strip(),
        ))
        try:
            lookup = clearance_hole(thread, fit)
        except UnknownThread:
            pass
        else:
            out.append(_mk(
                "ev_rule_hole_diameter", SemanticTarget.MOUNTING_HOLE_DIAMETER,
                EvidenceKind.DIAMETER, lookup.diameter_mm, "mm",
                source_name=lookup.citation, confidence=1.0,
                # derived from a standard, not annotated anywhere
                explicit=False,
                raw=f"{thread} {fit.value} clearance",
                method=ExtractionMethod.KNOWLEDGE_TABLE,
                detail=lookup.citation,
            ))

    # --- edge clearance: "at least 4 mm from every hole edge" --------------
    m = re.search(
        rf"at\s+least\s+({_NUM})\s*(mm|cm|in|inch|inches)\s+from\s+every\s+hole\s+edge",
        text, re.IGNORECASE,
    )
    if m:
        value_mm, unit = _to_mm(float(m.group(1)), m.group(2))
        original = None if unit == m.group(2).lower() else f"{m.group(1)} {m.group(2)}"
        out.append(_mk(
            "ev_txt_edge_clearance", SemanticTarget.MIN_HOLE_EDGE_CLEARANCE,
            EvidenceKind.CONSTRAINT, value_mm, unit,
            source_name=source_name, confidence=0.99, explicit=True,
            raw=m.group(0), original=original,
        ))

    # --- chamfer: "add 1 mm chamfers to the external edges" ----------------
    m = re.search(
        rf"({_NUM})\s*(mm|cm|in|inch|inches)\s+chamfers?", text, re.IGNORECASE
    )
    if m:
        value_mm, unit = _to_mm(float(m.group(1)), m.group(2))
        original = None if unit == m.group(2).lower() else f"{m.group(1)} {m.group(2)}"
        out.append(_mk(
            "ev_txt_chamfer", SemanticTarget.EXTERNAL_CHAMFER,
            EvidenceKind.FEATURE_CALLOUT, value_mm, unit,
            source_name=source_name, confidence=0.97, explicit=True,
            raw=m.group(0), original=original,
        ))

    # --- process: inferred, and flagged as such ----------------------------
    if re.search(r"machin|mill|chamfer", text, re.IGNORECASE):
        out.append(_mk(
            "ev_txt_process", SemanticTarget.MANUFACTURING_PROCESS,
            EvidenceKind.PROCESS_SPEC, "machining", None,
            source_name=source_name,
            # inferred from the presence of machined features, never stated
            confidence=0.72, explicit=False,
            raw="inferred from machined-feature callouts (chamfer)",
        ))

    return out
