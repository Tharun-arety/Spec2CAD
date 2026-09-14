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
_UNIT = r"mm|cm|in|inch|inches|millimet(?:re|er)s?"

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

    def add_length(
        ev_id: str,
        target: SemanticTarget,
        kind: EvidenceKind,
        raw_value: str,
        raw_unit: str,
        raw: str,
        *,
        confidence: float = 0.98,
        explicit: bool = True,
    ) -> None:
        value_mm, unit = _to_mm(float(raw_value), raw_unit)
        original = None if unit == raw_unit.lower() else f"{raw_value} {raw_unit}"
        out.append(_mk(
            ev_id, target, kind, value_mm, unit,
            source_name=source_name, confidence=confidence, explicit=explicit,
            raw=raw, original=original,
        ))

    # --- plate envelope: "60 mm wide, 40 mm high" ------------------------
    envelope = re.search(
        rf"({_NUM})\s*({_UNIT})\s+(?:wide|in\s+width)\s*[,;]?\s*"
        rf"(?:and\s+)?({_NUM})\s*({_UNIT})\s+(?:high|tall|in\s+height)",
        text, re.IGNORECASE,
    )
    if envelope:
        add_length(
            "ev_txt_plate_width", SemanticTarget.PLATE_WIDTH,
            EvidenceKind.LINEAR_DIMENSION, envelope.group(1), envelope.group(2),
            envelope.group(0),
        )
        add_length(
            "ev_txt_plate_height", SemanticTarget.PLATE_HEIGHT,
            EvidenceKind.LINEAR_DIMENSION, envelope.group(3), envelope.group(4),
            envelope.group(0),
        )
    else:
        # Compact engineering shorthand: "60 x 40 x 6 mm plate". The third
        # value is thickness; the dedicated material rule below still wins if
        # the prompt states thickness again next to a material.
        envelope = re.search(
            rf"({_NUM})\s*[x×]\s*({_NUM})\s*[x×]\s*({_NUM})\s*({_UNIT})\s+(?:mounting\s+)?plate",
            text, re.IGNORECASE,
        )
        if envelope:
            raw = envelope.group(0)
            unit = envelope.group(4)
            add_length("ev_txt_plate_width", SemanticTarget.PLATE_WIDTH,
                       EvidenceKind.LINEAR_DIMENSION, envelope.group(1), unit, raw)
            add_length("ev_txt_plate_height", SemanticTarget.PLATE_HEIGHT,
                       EvidenceKind.LINEAR_DIMENSION, envelope.group(2), unit, raw)
            add_length("ev_txt_plate_thickness_envelope", SemanticTarget.PLATE_THICKNESS,
                       EvidenceKind.LINEAR_DIMENSION, envelope.group(3), unit, raw)

    # --- rectangular mounting pattern: "44 mm by 24 mm ... pattern" ------
    pattern = re.search(
        rf"({_NUM})\s*({_UNIT})?\s*(?:x|×|by)\s*({_NUM})\s*({_UNIT})\s+"
        rf"(?:rectangular\s+)?(?:mounting\s+|hole\s+)?pattern",
        text, re.IGNORECASE,
    )
    if pattern:
        first_unit = pattern.group(2) or pattern.group(4)
        raw = pattern.group(0)
        add_length("ev_txt_hole_spacing_x", SemanticTarget.HOLE_SPACING_X,
                   EvidenceKind.HOLE_PATTERN, pattern.group(1), first_unit, raw)
        add_length("ev_txt_hole_spacing_y", SemanticTarget.HOLE_SPACING_Y,
                   EvidenceKind.HOLE_PATTERN, pattern.group(3), pattern.group(4), raw)

    # --- mounting-hole count ----------------------------------------------
    number_words = {
        "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "eight": 8,
    }
    count_match = re.search(
        r"\b(one|two|three|four|five|six|eight|\d+)\s+(?:normal-clearance\s+)?"
        r"(?:mounting\s+)?holes?\b",
        text, re.IGNORECASE,
    )
    if count_match:
        token = count_match.group(1).lower()
        count = number_words.get(token, int(token) if token.isdigit() else 0)
        out.append(_mk(
            "ev_txt_hole_count", SemanticTarget.MOUNTING_HOLE_COUNT,
            EvidenceKind.COUNT, count, None,
            source_name=source_name, confidence=0.99, explicit=True,
            raw=count_match.group(0),
        ))
    elif pattern:
        # A rectangular corner pattern means four locations in the compiler's
        # supported vocabulary. It is marked inferred rather than pretending
        # the user literally supplied the count.
        out.append(_mk(
            "ev_txt_hole_count_pattern", SemanticTarget.MOUNTING_HOLE_COUNT,
            EvidenceKind.COUNT, 4, None,
            source_name=source_name, confidence=0.88, explicit=False,
            raw=pattern.group(0),
        ))

    # --- centre/shaft opening: "20 mm centre opening" --------------------
    opening = re.search(
        rf"({_NUM})\s*({_UNIT})\s+(?:diameter\s+)?"
        rf"(?:(?:centre|center|central|shaft)\s+(?:opening|hole)|opening\s+diameter)",
        text, re.IGNORECASE,
    )
    if opening:
        add_length(
            "ev_txt_shaft_opening", SemanticTarget.SHAFT_OPENING_DIAMETER,
            EvidenceKind.DIAMETER, opening.group(1), opening.group(2), opening.group(0),
        )

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
        # Avoid a duplicate thickness candidate when compact WxHxT shorthand
        # and the material phrase refer to the same literal.
        if not any(e.target is SemanticTarget.PLATE_THICKNESS for e in out):
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
