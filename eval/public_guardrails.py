"""Deterministic public-boundary and API-cost evaluation suite."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import ValidationError

from spec2cad.extractors.base import model_max_output_tokens, model_timeout_seconds
from spec2cad.public_guardrails import BoundedRunCache, DailyAIBudget, SlidingWindowLimiter
from spec2cad.schemas.cad_ir import BoxOp, CADProgram, NumberLiteral, lit
from spec2cad.schemas.evidence import EvidenceSet
from spec2cad.store import Store


@dataclass(frozen=True)
class GuardrailOutcome:
    category: str
    assertion: str
    passed: bool
    actual: object
    expected: object


def run_suite() -> list[GuardrailOutcome]:
    out: list[GuardrailOutcome] = []

    clock_value = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: clock_value[0])
    first = limiter.admit("client")[0]
    second = limiter.admit("client")[0]
    third = limiter.admit("client")[0]
    out.append(GuardrailOutcome("rate_limit", "burst is capped", first and second and not third, [first, second, third], [True, True, False]))
    clock_value[0] = 61
    reset = limiter.admit("client")[0]
    out.append(GuardrailOutcome("rate_limit", "window resets", reset, reset, True))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = Store(root / "usage.db")
        budget = DailyAIBudget(store, client_limit=2, global_limit=3)
        budget.reserve("hashed-a", 2)
        client_refused = False
        try:
            budget.reserve("hashed-a", 1)
        except ValueError as exc:
            client_refused = str(exc) == "client_daily_limit"
        out.append(GuardrailOutcome("ai_budget", "per-client daily cap", client_refused, client_refused, True))
        budget.reserve("hashed-b", 1)
        global_refused = False
        try:
            budget.reserve("hashed-c", 1)
        except ValueError as exc:
            global_refused = str(exc) == "global_daily_limit"
        out.append(GuardrailOutcome("ai_budget", "global daily cap", global_refused, global_refused, True))

        run_id = store.create_run(root, EvidenceSet(items=[]), "eval")
        out.append(GuardrailOutcome("access", "run id has 128 bits", len(run_id) == 32, len(run_id), 32))

    cache = BoundedRunCache(2)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    evicted = cache.get("a") is None and cache.get("b") == 2 and cache.get("c") == 3
    out.append(GuardrailOutcome("resource_caps", "B-Rep cache is bounded", evicted, evicted, True))

    finite_refused = False
    try:
        NumberLiteral(value=float("inf"))
    except ValidationError:
        finite_refused = True
    out.append(GuardrailOutcome("resource_caps", "nonfinite CAD value refused", finite_refused, finite_refused, True))

    operation = BoxOp(id="body", width=lit(1), height=lit(1), depth=lit(1))
    flood_refused = False
    try:
        CADProgram(part_name="flood", operations=[operation] * 65)
    except ValidationError:
        flood_refused = True
    out.append(GuardrailOutcome("resource_caps", "operation flood refused", flood_refused, flood_refused, True))

    output_cap = model_max_output_tokens()
    timeout = model_timeout_seconds()
    out.append(GuardrailOutcome("model_controls", "output tokens capped", output_cap <= 8000, output_cap, "<= 8000"))
    out.append(GuardrailOutcome("model_controls", "provider timeout capped", timeout <= 120, timeout, "<= 120"))
    return out


def write_reports(outcomes: list[GuardrailOutcome], root: Path) -> None:
    payload = {
        "all_passed": all(item.passed for item in outcomes),
        "passed": sum(item.passed for item in outcomes),
        "total": len(outcomes),
        "outcomes": [asdict(item) for item in outcomes],
    }
    (root / "public_guardrail_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    lines = [
        "# Public guardrail evaluation", "",
        f"Result: **{payload['passed']}/{payload['total']} passed**", "",
        "| Category | Assertion | Result |", "|---|---|---|",
    ]
    lines.extend(
        f"| {item.category} | {item.assertion} | {'PASS' if item.passed else 'FAIL'} |"
        for item in outcomes
    )
    (root / "public_guardrail_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
