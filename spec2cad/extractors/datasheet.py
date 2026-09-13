"""Datasheet extraction via PyMuPDF text layout.

This path is genuinely real on every run, with or without an API key. PyMuPDF
gives us the words *and their rectangles*, so the page number and highlight box
attached to each piece of evidence are the actual coordinates of the actual
text -- not a plausible-looking box we drew afterwards. That is what makes the
"click a value, see where it came from" feature honest.

The parser is deliberately narrow: a table of label patterns, each with an
explicit value parser. It reads the rows it knows and stays silent about
everything else, rather than scraping numbers and guessing at their meaning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

import fitz

from spec2cad.fusion.source_policy import authority_for
from spec2cad.schemas.evidence import (
    Evidence,
    EvidenceKind,
    ExtractionMethod,
    SemanticTarget,
    SourceModality,
    SourceRef,
)

# The datasheet column layout: values start right of this x coordinate.
VALUE_COLUMN_X = 300.0


# Words within this many points of each other vertically are one visual row.
# PyMuPDF's own (block, line) numbering is not usable here: a table row's label
# and its value are emitted as separate text runs and land on different line
# numbers despite sharing a baseline, so grouping by them splits every row.
ROW_TOLERANCE_PT = 3.0


@dataclass(frozen=True)
class Row:
    """One reconstructed table row, split at the value column."""

    page: int                      # 1-based
    words: list[tuple[float, float, float, float, str]]

    @property
    def label_text(self) -> str:
        return " ".join(w[4] for w in self.words if w[0] < VALUE_COLUMN_X)

    @property
    def text(self) -> str:
        return " ".join(w[4] for w in self.words)

    def value_region(self) -> Optional[tuple[float, float, float, float]]:
        """Bounding box of the words in the value column."""
        vals = [w for w in self.words if w[0] >= VALUE_COLUMN_X]
        if not vals:
            return None
        return (
            min(w[0] for w in vals), min(w[1] for w in vals),
            max(w[2] for w in vals), max(w[3] for w in vals),
        )

    def value_text(self) -> str:
        return " ".join(w[4] for w in self.words if w[0] >= VALUE_COLUMN_X)


def iter_rows(pdf_path: Path) -> Iterator[Row]:
    """Yield visual rows, clustering words that share a baseline."""
    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc):
            words = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
            cluster: list = []
            cluster_y: Optional[float] = None
            for x0, y0, x1, y1, word, *_ in words:
                if cluster_y is None or abs(y0 - cluster_y) <= ROW_TOLERANCE_PT:
                    cluster.append((x0, y0, x1, y1, word))
                    cluster_y = y0 if cluster_y is None else cluster_y
                else:
                    yield Row(page=page_index + 1, words=sorted(cluster, key=lambda w: w[0]))
                    cluster = [(x0, y0, x1, y1, word)]
                    cluster_y = y0
            if cluster:
                yield Row(page=page_index + 1, words=sorted(cluster, key=lambda w: w[0]))


# --------------------------------------------------------------------------
# Value parsers
# --------------------------------------------------------------------------

_NUM = r"[-+]?\d+(?:\.\d+)?"


def _first_number(text: str) -> Optional[float]:
    m = re.search(_NUM, text)
    return float(m.group()) if m else None


def _pattern_pair(text: str) -> Optional[tuple[float, float]]:
    """Parse '31 x 31 mm' -> (31.0, 31.0)."""
    m = re.search(rf"({_NUM})\s*[x×]\s*({_NUM})", text, re.IGNORECASE)
    return (float(m.group(1)), float(m.group(2))) if m else None


def _thread(text: str) -> Optional[str]:
    m = re.search(r"\bM\d+(?:\.\d+)?\b", text, re.IGNORECASE)
    return m.group().upper() if m else None


@dataclass(frozen=True)
class Rule:
    """A table-row rule.

    `label` is anchored to the START of the row's label column. Anchoring is
    what stops running prose from matching: page 4 contains the sentence
    "Mating plates must clear the pilot boss diameter listed in section 3.",
    which an unanchored search happily matched, scraping "3" out of "section 3."
    A real table row begins with its label; a sentence mentioning the label
    does not.
    """

    label: str
    emit: Callable[[Row], list[tuple[SemanticTarget, EvidenceKind, object, Optional[str]]]]


def _r_pattern(line: Row):
    pair = _pattern_pair(line.value_text())
    if pair is None:
        return []
    x, y = pair
    return [
        (SemanticTarget.HOLE_SPACING_X, EvidenceKind.HOLE_PATTERN, x, "mm"),
        (SemanticTarget.HOLE_SPACING_Y, EvidenceKind.HOLE_PATTERN, y, "mm"),
    ]


def _r_count(line: Row):
    n = _first_number(line.value_text())
    return [] if n is None else [
        (SemanticTarget.MOUNTING_HOLE_COUNT, EvidenceKind.COUNT, int(n), None)
    ]


def _r_thread(line: Row):
    t = _thread(line.value_text())
    return [] if t is None else [
        (SemanticTarget.MOUNTING_THREAD_SPEC, EvidenceKind.THREAD_CALLOUT, t, None)
    ]


def _r_boss(line: Row):
    d = _first_number(line.value_text())
    return [] if d is None else [
        (SemanticTarget.MOTOR_BOSS_DIAMETER, EvidenceKind.DIAMETER, d, "mm")
    ]


RULES: list[Rule] = [
    Rule(r"^mounting\s+hole\s+pattern", _r_pattern),
    Rule(r"^number\s+of\s+mounting\s+holes", _r_count),
    Rule(r"^mounting\s+screw\s+size", _r_thread),
    Rule(r"^pilot\s+boss\s+diameter", _r_boss),
]


def extract_datasheet(pdf_path: str | Path, entity: str = "motor_mount") -> list[Evidence]:
    """Extract known mechanical facts from a datasheet PDF.

    Every returned item carries a true page number and a true rectangle, taken
    from PyMuPDF's own word geometry.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"datasheet not found: {pdf_path}")

    out: list[Evidence] = []
    seen: set[SemanticTarget] = set()

    for line in iter_rows(pdf_path):
        label = line.label_text.strip()
        value_text = line.value_text().strip()
        if not value_text:
            continue          # not a table row: nothing in the value column
        for rule in RULES:
            if not re.search(rule.label, label, re.IGNORECASE):
                continue
            region = line.value_region()
            for target, kind, value, unit in rule.emit(line):
                if target in seen:      # first occurrence wins; datasheets repeat
                    continue
                seen.add(target)
                out.append(
                    Evidence(
                        id=f"ev_ds_{target.value}",
                        entity=entity,
                        kind=kind,
                        target=target,
                        value=value,
                        unit=unit,
                        source=SourceRef(
                            file=pdf_path.name,
                            modality=SourceModality.DATASHEET,
                            page=line.page,
                            region=region,
                        ),
                        extraction_method=ExtractionMethod.PDF_TEXT_LAYOUT,
                        # High: the text layer is read exactly, not inferred.
                        confidence=0.97,
                        # Ownership decided centrally by the source policy.
                        authority=authority_for(
                            SourceModality.DATASHEET, target, True
                        ),
                        is_explicit_annotation=True,
                        raw_text=line.text.strip(),
                    )
                )
    return out
