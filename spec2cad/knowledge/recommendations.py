"""Rounding helpers for repair proposals.

Naming note: an earlier draft called this a "stock size" lookup. That was wrong
and has been corrected. There is no universal stock series for an arbitrary
machined plate outline -- plate *stock thickness* is standardised, but a width
you mill to is whatever you cut it to. What this module actually does is round a
computed minimum up to a tidy increment so the recommendation is memorable and
leaves a little margin.

It is therefore called a *recommended rounded width*, and the reason string says
so, rather than implying a standards basis that does not exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_INCREMENT_MM = 5.0


@dataclass(frozen=True)
class Recommendation:
    minimum_mm: float
    recommended_mm: float
    increment_mm: float

    @property
    def margin_mm(self) -> float:
        return self.recommended_mm - self.minimum_mm

    def describe(self) -> str:
        return (
            f"minimum feasible {self.minimum_mm:g} mm; "
            f"recommended {self.recommended_mm:g} mm "
            f"(rounded up to the next {self.increment_mm:g} mm increment, "
            f"leaving {self.margin_mm:g} mm margin)"
        )


def recommended_rounded_width(
    minimum_mm: float, increment_mm: float = DEFAULT_INCREMENT_MM
) -> Recommendation:
    """Round a computed minimum up to the next tidy increment.

    If the minimum already sits exactly on an increment, step up one full
    increment so the recommendation always carries margin rather than landing
    precisely on a limit.
    """
    if minimum_mm <= 0:
        raise ValueError(f"minimum must be positive, got {minimum_mm}")
    if increment_mm <= 0:
        raise ValueError(f"increment must be positive, got {increment_mm}")

    steps = math.floor(minimum_mm / increment_mm) + 1
    recommended = steps * increment_mm
    return Recommendation(
        minimum_mm=round(minimum_mm, 6),
        recommended_mm=round(recommended, 6),
        increment_mm=increment_mm,
    )
