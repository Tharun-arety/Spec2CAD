"""Run the evaluation suites and write eval/report.md.

Two suites, deliberately never averaged together:

  Deterministic pipeline suite  -- no API calls, fully reproducible, runs in CI.
  Real extractor suite          -- needs a vision API key, is non-deterministic,
                                   and is reported with run-to-run spread.

    python -m eval.run_eval                 # deterministic only
    python -m eval.run_eval --real 3        # plus 3 real extraction runs
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from eval.metrics import (
    ExtractionScore,
    PipelineScore,
    VarianceReport,
    score_extraction,
)
from spec2cad.extractors.base import VisionBackend, backend_label, select_backend
from spec2cad.extractors.drawing import extract_sketch
from spec2cad.fusion.conflict_detector import edge_clearance, minimum_plate_dimension
from spec2cad.knowledge.fastener_tables import clearance_hole
from spec2cad.knowledge.recommendations import recommended_rounded_width
from spec2cad.pipeline import repair, run, verify_exported_step
from spec2cad.cad.executor import export_step
from spec2cad.repair.repair_planner import (
    ProposalSafety,
    UnsafeRepairRequiresAcknowledgement,
    apply_repair,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "motor_adapter"
REPORT = ROOT / "eval" / "report.md"


# --------------------------------------------------------------------------
# Deterministic pipeline suite
# --------------------------------------------------------------------------


def deterministic_suite() -> PipelineScore:
    score = PipelineScore()

    # --- the arithmetic the demo turns on ---
    score.check("edge clearance at 40 mm width", 2.8,
                edge_clearance(40.0, 31.0, 3.4), tol=1e-9)
    score.check("minimum feasible width", 42.4,
                minimum_plate_dimension(31.0, 3.4, 4.0), tol=1e-9)
    score.check("recommended rounded width", 45.0,
                recommended_rounded_width(42.4).recommended_mm, tol=1e-9)
    score.check("edge clearance at 45 mm width", 5.3,
                edge_clearance(45.0, 31.0, 3.4), tol=1e-9)
    score.check("M3 medium clearance via ISO 273", 3.4,
                clearance_hole("M3").diameter_mm, tol=1e-9)

    # --- v1: extraction, fusion, conflict ---
    result = run(EXAMPLE / "sketch.png", EXAMPLE / "motor_datasheet.pdf",
                 EXAMPLE / "requirement.txt", backend_override="fixture")
    v1 = result.revision(1)

    ds_spacing = [e for e in result.evidence.items
                  if e.target.value == "hole_spacing_x"][0]
    score.check("hole spacing read from datasheet", 31.0, ds_spacing.value, tol=1e-9)
    score.check("datasheet page attributed", 3, ds_spacing.source.page)
    score.check("datasheet bbox captured", True, ds_spacing.source.region is not None)
    score.check("boss diameter not scraped from page-4 prose", 22.0,
                [e for e in result.evidence.items
                 if e.target.value == "motor_boss_diameter"][0].value, tol=1e-9)

    # --- v1: the invalid candidate is built, not refused ---
    score.check("invalid candidate still builds", True, v1.execution is not None)
    score.check("candidate is a valid solid", True,
                bool(v1.execution.shape.isValid()))
    score.check("single body", 1, len(v1.execution.shape.Solids()))

    measured = v1.measured[-1].get("req_edge_clearance")
    score.check("clearance MEASURED on the solid", 2.8,
                measured.measured_value, tol=1e-6)

    predicted = v1.preflight.get("pre_edge_clearance_x")
    score.check("preflight prediction matches measurement", True,
                abs(predicted.measured_value - measured.measured_value) < 1e-6)

    score.check("failure classed as a constraint conflict", "constraint_conflict",
                predicted.conflict_class.value)
    score.check("no source conflict claimed", "pass",
                v1.preflight.get("pre_source_conflicts").status.value)

    # --- v1: the gate blocks ---
    score.check("release blocked at v1", False, v1.decision.step_export_allowed)
    score.check("mesh marked provisional", True,
                "PROVISIONAL" in (v1.decision.mesh_watermark or ""))

    # --- proposals ---
    safe = [p for p in v1.proposals if p.safety is ProposalSafety.SAFE]
    unsafe = [p for p in v1.proposals if p.safety is ProposalSafety.UNSAFE]
    score.check("two safe proposals offered", 2, len(safe))
    score.check("unsafe options still surfaced", 2, len(unsafe))
    score.check("every unsafe option states its consequence", True,
                all(p.consequence for p in unsafe))

    refused = False
    try:
        apply_repair(v1.intent, unsafe[0], approved_by="eval")
    except UnsafeRepairRequiresAcknowledgement:
        refused = True
    score.check("unsafe repair refused without acknowledgement", True, refused)

    interface = {"hole_spacing_x", "hole_spacing_y",
                 "mounting_hole_diameter", "mounting_hole_count"}
    score.check("safe repairs never touch the motor interface", True,
                all(not (set(p.updates) & interface) for p in safe))

    # --- v2: repair, regeneration, release ---
    after = repair(result, "widen_to_recommended", approved_by="eval")
    v2 = after.revision(2)

    score.check("v2 derives from v1", 1, v2.intent.parent_revision)
    score.check("v1 remains at 40 mm", 40.0,
                after.revision(1).intent.value_of("plate_width"), tol=1e-9)
    score.check("v2 is 45 mm", 45.0, v2.intent.value_of("plate_width"), tol=1e-9)
    score.check("change recorded with before/after", (40.0, 45.0),
                (v2.intent.changes[0].before, v2.intent.changes[0].after))
    score.check("approver recorded", "eval", v2.intent.approved_by)

    v2_clearance = v2.measured[-1].get("req_edge_clearance")
    score.check("v2 clearance measured", 5.3, v2_clearance.measured_value, tol=1e-6)
    score.check("release authorised at v2", True, v2.decision.step_export_allowed)
    score.check("no measured failures at v2", 0,
                sum(len(r.failures) for r in v2.measured))

    # --- the exported artifact itself ---
    out = ROOT / "build" / "eval"
    step = export_step(v2.execution, out / "eval_v2.step")
    reports = verify_exported_step(step, v2.intent)
    score.check("re-imported STEP re-validates", True,
                all(r.passed for r in reports))

    return score


# --------------------------------------------------------------------------
# Real extractor suite
# --------------------------------------------------------------------------


def real_extractor_suite(repeats: int) -> tuple[VarianceReport, str]:
    backend = select_backend()
    if backend is VisionBackend.FIXTURE:
        return VarianceReport(), (
            "skipped: no vision API key configured. Set OPENAI_API_KEY or "
            "ANTHROPIC_API_KEY in .env to measure real extraction accuracy."
        )

    truth = json.loads((EXAMPLE / "sketch.truth.json").read_text(encoding="utf-8"))
    report = VarianceReport()
    notes: list[str] = []

    for i in range(repeats):
        try:
            # allow_fallback=False: a failure must be an honest failure, never a
            # fixture quietly standing in for a real extraction
            extraction = extract_sketch(
                EXAMPLE / "sketch.png", allow_fallback=False
            )
            report.scores.append(
                score_extraction(
                    extraction.evidence, truth["facts"], backend_label(backend)
                )
            )
        except Exception as exc:
            notes.append(f"run {i + 1} failed: {type(exc).__name__}: {exc}")
            report.scores.append(ExtractionScore(outcomes=[], backend=str(backend.value)))

    return report, "; ".join(notes) if notes else ""


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def write_report(pipeline: PipelineScore, variance: VarianceReport, note: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Spec2CAD evaluation report",
        "",
        f"Generated {now}",
        "",
        "Two suites are reported separately and never averaged together. One measures",
        "the pipeline; the other measures an extractor. Combining them would produce a",
        "number that describes neither.",
        "",
        "## 1. Deterministic pipeline suite",
        "",
        "Fixed evidence in, no API calls, fully reproducible. This is what runs in CI.",
        "",
        f"**{pipeline.summary()}**",
        "",
        "| Check | Expected | Actual | Result |",
        "|---|---|---|---|",
    ]
    for o in pipeline.outcomes:
        mark = "pass" if o.passed else "**FAIL**"
        lines.append(f"| {o.name} | `{o.expected}` | `{o.actual}` | {mark} |")

    lines += [
        "",
        "## 2. Real extractor suite",
        "",
        "Genuine multimodal extraction against the sketch ground truth. Non-deterministic,",
        "so it is reported across repeats with the spread shown rather than as a single",
        "figure. Fixture-replayed evidence is structurally barred from this suite:",
        "`score_extraction` raises `FixtureEvidenceInMetrics` rather than scoring a",
        "recording, because replaying a recording measures the recording.",
        "",
    ]
    if not variance.scores:
        lines += [f"_{note}_", ""]
    else:
        lines += [f"**{variance.summary()}**", "", "| Run | Accuracy | Missed |", "|---|---|---|"]
        for i, s in enumerate(variance.scores, 1):
            lines.append(f"| {i} | {s.accuracy:.0%} | {', '.join(s.missed) or '—'} |")
        if note:
            lines += ["", f"Notes: {note}"]
        lines += [
            "",
            "| Target | Expected | Last run | Correct |",
            "|---|---|---|---|",
        ]
        for o in variance.scores[-1].outcomes:
            lines.append(
                f"| {o.target} | `{o.expected}` | `{o.predicted}` | "
                f"{'yes' if o.correct else 'no'} |"
            )

    lines += [
        "",
        "## 3. Failure analysis",
        "",
        "Stated plainly, because a prototype with hidden limitations is worse than a",
        "smaller one with known ones.",
        "",
        "**What is genuinely measured**",
        "",
        "- Datasheet extraction is real on every run: PyMuPDF returns the words and their",
        "  rectangles, so the page number and highlight box are the actual coordinates of",
        "  the actual text. This holds with or without an API key.",
        "- All dimensional validation is read off the B-Rep. Hole diameters and centres",
        "  come from `Edge.radius()`/`Edge.Center()`, extents from planar face positions,",
        "  and material integrity from measured-vs-analytic volume (agreement to 1e-9 mm3).",
        "  None of it echoes the input parameters, so a wrongly built feature fails.",
        "",
        "**Known limitations**",
        "",
        "- Without a vision API key, sketch evidence is replayed from a recorded fixture.",
        "  This is labelled on every row in the UI and excluded from extraction metrics,",
        "  but it means the offline demo does not exercise drawing understanding at all.",
        "- The datasheet parser is a narrow table-rule reader, not a general document",
        "  parser. It reads the rows it knows and stays silent otherwise. An unanchored",
        "  version of it scraped `3` out of the sentence \"listed in section 3\" on page 4;",
        "  that is now fixed by anchoring labels to the row start, and regression-tested,",
        "  but the class of error is inherent to rule-based extraction.",
        "- The geometry vocabulary is four operations (box, hole, rectangular hole pattern,",
        "  chamfer) and the hole pattern supports exactly four corner holes. Anything else",
        "  raises rather than approximating.",
        "- Only one part family is supported. No GD&T, tolerancing, assemblies, or",
        "  alternate motor frames.",
        "- Preflight and measured validation are cross-checked against each other, but both",
        "  encode the same clearance formula. A conceptual error in that formula would not",
        "  be caught by their agreement.",
        "",
        "**Deliberately deferred**",
        "",
        "The 15-case matrix and the perturbation battery (inch inputs, relocated and",
        "removed dimensions, rotated sketches, contradictory text, altered hole patterns)",
        "were cut from v1 in favour of one slice that works end to end and is honestly",
        "reported. Unit normalisation and the source-adjudication path are implemented and",
        "unit-tested, so those perturbations are the natural next increment.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval")
    parser.add_argument("--real", type=int, default=0, metavar="N",
                        help="number of real extraction runs (needs an API key)")
    args = parser.parse_args(argv)

    print("running deterministic pipeline suite ...")
    pipeline = deterministic_suite()
    for o in pipeline.outcomes:
        if not o.passed:
            print(f"  {o.line()}")
    print(f"  {pipeline.summary()}")

    variance, note = VarianceReport(), ""
    if args.real > 0:
        print(f"running real extractor suite ({args.real} repeats) ...")
        variance, note = real_extractor_suite(args.real)
        print(f"  {variance.summary() if variance.scores else note}")
    else:
        _, note = real_extractor_suite(0)

    write_report(pipeline, variance, note)
    print(f"\nwrote {REPORT.relative_to(ROOT)}")
    return 0 if pipeline.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
