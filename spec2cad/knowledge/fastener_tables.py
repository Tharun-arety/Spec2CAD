"""Fastener clearance-hole lookups.

Values follow ISO 273 "Fasteners -- Clearance holes for bolts and screws".
Every derivation returns the clause it came from so the resulting Evidence can
cite a standard instead of asserting a number. This is the difference between
"the model said 3.4" and "ISO 273 medium series specifies 3.4 for M3".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FitClass(str, Enum):
    CLOSE = "close"
    MEDIUM = "medium"    # the default; commonly called "normal clearance"
    COARSE = "coarse"


# thread designation -> {fit class: clearance hole diameter in mm}
ISO_273_CLEARANCE_MM: dict[str, dict[FitClass, float]] = {
    "M1.6": {FitClass.CLOSE: 1.7, FitClass.MEDIUM: 1.8, FitClass.COARSE: 2.0},
    "M2": {FitClass.CLOSE: 2.2, FitClass.MEDIUM: 2.4, FitClass.COARSE: 2.6},
    "M2.5": {FitClass.CLOSE: 2.7, FitClass.MEDIUM: 2.9, FitClass.COARSE: 3.1},
    "M3": {FitClass.CLOSE: 3.2, FitClass.MEDIUM: 3.4, FitClass.COARSE: 3.6},
    "M4": {FitClass.CLOSE: 4.3, FitClass.MEDIUM: 4.5, FitClass.COARSE: 4.8},
    "M5": {FitClass.CLOSE: 5.3, FitClass.MEDIUM: 5.5, FitClass.COARSE: 5.8},
    "M6": {FitClass.CLOSE: 6.4, FitClass.MEDIUM: 6.6, FitClass.COARSE: 7.0},
    "M8": {FitClass.CLOSE: 8.4, FitClass.MEDIUM: 9.0, FitClass.COARSE: 10.0},
    "M10": {FitClass.CLOSE: 10.5, FitClass.MEDIUM: 11.0, FitClass.COARSE: 12.0},
}

# Wording in requirement text -> fit class. "normal" is the colloquial name for
# the medium series and is what the demo requirement uses.
FIT_SYNONYMS: dict[str, FitClass] = {
    "close": FitClass.CLOSE,
    "fine": FitClass.CLOSE,
    "normal": FitClass.MEDIUM,
    "medium": FitClass.MEDIUM,
    "standard": FitClass.MEDIUM,
    "coarse": FitClass.COARSE,
    "loose": FitClass.COARSE,
}


@dataclass(frozen=True)
class ClearanceLookup:
    thread: str
    fit: FitClass
    diameter_mm: float
    citation: str

    def describe(self) -> str:
        return (
            f"{self.thread} {self.fit.value} clearance = "
            f"{self.diameter_mm} mm ({self.citation})"
        )


class UnknownThread(KeyError):
    """Raised for a thread designation not present in the table."""


def clearance_hole(thread: str, fit: FitClass = FitClass.MEDIUM) -> ClearanceLookup:
    """Look up a clearance-hole diameter, or fail loudly.

    Never guesses or interpolates: an unknown thread is an extraction problem to
    surface, not a number to invent.
    """
    key = thread.strip().upper()
    if key not in ISO_273_CLEARANCE_MM:
        raise UnknownThread(
            f"no ISO 273 clearance entry for thread {thread!r}; "
            f"known: {sorted(ISO_273_CLEARANCE_MM)}"
        )
    return ClearanceLookup(
        thread=key,
        fit=fit,
        diameter_mm=ISO_273_CLEARANCE_MM[key][fit],
        citation=f"ISO 273 {fit.value} series",
    )


def fit_from_text(text: str, default: FitClass = FitClass.MEDIUM) -> FitClass:
    """Map requirement wording such as 'normal-clearance' onto a fit class."""
    lowered = text.lower()
    for word, fit in FIT_SYNONYMS.items():
        if word in lowered:
            return fit
    return default
