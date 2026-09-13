"""Scoring, with the two suites kept structurally apart.

There are two very different things one might call "accuracy" here, and mixing
them would produce a number that means nothing:

  Real extractor evaluation
      How well does genuine multimodal extraction read the drawing? Requires an
      API key, costs money, and is NOT deterministic -- so it is reported across
      repeated runs with the spread shown, never as a single figure.

  Deterministic pipeline evaluation
      Given fixed evidence, does fusion -> compile -> measure -> repair behave
      correctly? Fully reproducible, no API calls, safe to run in CI.

The hard rule is enforced in code rather than by convention: evidence replayed
from a fixture cannot contribute to an extraction score. Replaying a recording
measures the recording, not the extractor, and a number built from it would
overstate the system's capability.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable, Optional

from spec2cad.schemas.evidence import Evidence, SemanticTarget


class FixtureEvidenceInMetrics(AssertionError):
    """Raised when fixture-replayed evidence reaches an extraction score."""


@dataclass
class TargetOutcome:
    target: str
    expected: object
    predicted: object
    correct: bool
    note: str = ""


@dataclass
class ExtractionScore:
    """Accuracy of a real extractor against ground truth."""

    outcomes: list[TargetOutcome] = field(default_factory=list)
    backend: str = ""

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def correct(self) -> int:
        return sum(1 for o in self.outcomes if o.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def missed(self) -> list[str]:
        return [o.target for o in self.outcomes if not o.correct]

    def summary(self) -> str:
        return (
            f"{self.correct}/{self.total} targets correct "
            f"({self.accuracy:.0%}) via {self.backend}"
        )


def _matches(expected: object, predicted: object, tol: float = 1e-6) -> bool:
    if predicted is None:
        return False
    if isinstance(expected, (int, float)) and isinstance(predicted, (int, float)):
        return abs(float(expected) - float(predicted)) <= tol
    return str(expected).strip().lower() == str(predicted).strip().lower()


def score_extraction(
    predicted: Iterable[Evidence],
    truth_facts: list[dict],
    backend: str = "",
) -> ExtractionScore:
    """Score real extraction against ground truth.

    Refuses outright to score fixture-replayed evidence.
    """
    predicted = list(predicted)

    offenders = [e.id for e in predicted if e.is_fixture]
    if offenders:
        raise FixtureEvidenceInMetrics(
            "refusing to compute extraction accuracy from fixture-replayed evidence "
            f"({', '.join(offenders)}). A recording cannot measure an extractor. "
            "Configure OPENAI_API_KEY or ANTHROPIC_API_KEY and re-run, or use the "
            "deterministic pipeline suite instead."
        )

    by_target: dict[str, Evidence] = {e.target.value: e for e in predicted}
    outcomes: list[TargetOutcome] = []

    for fact in truth_facts:
        target = fact["target"]
        expected = fact["value"]
        found = by_target.get(target)
        got = found.value if found else None
        outcomes.append(TargetOutcome(
            target=target, expected=expected, predicted=got,
            correct=_matches(expected, got),
            note="not reported" if found is None else "",
        ))

    # Reporting something the drawing does not support is also an error.
    truth_targets = {f["target"] for f in truth_facts}
    for target, ev in by_target.items():
        if target not in truth_targets:
            outcomes.append(TargetOutcome(
                target=target, expected=None, predicted=ev.value,
                correct=False, note="hallucinated: not present in ground truth",
            ))

    return ExtractionScore(outcomes=outcomes, backend=backend)


@dataclass
class VarianceReport:
    """Run-to-run spread for a non-deterministic extractor."""

    scores: list[ExtractionScore] = field(default_factory=list)

    @property
    def accuracies(self) -> list[float]:
        return [s.accuracy for s in self.scores]

    @property
    def mean(self) -> float:
        return statistics.fmean(self.accuracies) if self.accuracies else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.accuracies) if len(self.accuracies) > 1 else 0.0

    @property
    def worst(self) -> float:
        return min(self.accuracies) if self.accuracies else 0.0

    @property
    def best(self) -> float:
        return max(self.accuracies) if self.accuracies else 0.0

    def summary(self) -> str:
        if not self.scores:
            return "no runs"
        return (
            f"{len(self.scores)} runs: mean {self.mean:.0%}, "
            f"sd {self.stdev:.3f}, range {self.worst:.0%}-{self.best:.0%}"
        )


@dataclass
class PipelineOutcome:
    """One deterministic pipeline assertion."""

    name: str
    expected: object
    actual: object
    passed: bool

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.name}: expected {self.expected}, got {self.actual}"


@dataclass
class PipelineScore:
    outcomes: list[PipelineOutcome] = field(default_factory=list)

    def check(self, name: str, expected: object, actual: object, tol: Optional[float] = None):
        ok = (
            abs(float(expected) - float(actual)) <= tol
            if tol is not None and isinstance(expected, (int, float))
            else expected == actual
        )
        self.outcomes.append(PipelineOutcome(name, expected, actual, ok))
        return ok

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total

    def summary(self) -> str:
        return f"{self.passed}/{self.total} deterministic checks passed"
