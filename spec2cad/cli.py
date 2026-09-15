"""Command-line driver for the demo.

    python -m spec2cad.cli examples/motor_adapter
    python -m spec2cad.cli examples/motor_adapter --approve widen_to_recommended
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spec2cad.cad.executor import export_step, export_stl
from spec2cad.pipeline import RevisionResult, RunResult, repair, run, verify_exported_step
from spec2cad.schemas.report import CheckStatus

TICK = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skipped": "SKIP"}


def _rule(title: str = "", width: int = 78) -> None:
    if title:
        print(f"\n{title}")
        print("-" * width)
    else:
        print("-" * width)


def print_evidence(result: RunResult) -> None:
    _rule("EVIDENCE")
    print(f"{'parameter':<24}{'value':<12}{'source':<22}{'conf':<7}{'auth':<12}method")
    print("-" * 78)
    for e in sorted(result.evidence.items, key=lambda x: x.target.value):
        page = f" p.{e.source.page}" if e.source.page else ""
        src = f"{e.source.modality.value}{page}"
        unit = f" {e.unit}" if e.unit else ""
        print(
            f"{e.target.value:<24}{str(e.value) + unit:<12}{src:<22}"
            f"{e.confidence:<7.2f}{e.authority.value:<12}{e.extraction_method.value}"
        )
    print(f"\nsketch backend: {result.sketch_backend}")
    if result.sketch_fell_back:
        print(f"  NOTE: fell back to fixture after failure: {result.sketch_fallback_reason}")
    if result.evidence.contains_fixture_data:
        print("  NOTE: some evidence is replayed from a recorded fixture and is")
        print("        excluded from any reported extraction-accuracy figure.")


def print_revision(rev: RevisionResult) -> None:
    _rule(f"DESIGN INTENT v{rev.revision}  --  {rev.intent.lineage_summary()}")
    print(f"{'parameter':<26}{'value':<12}{'status':<24}provenance")
    for name, p in rev.intent.parameters.items():
        val = f"{p.value}{' ' + p.unit if p.unit else ''}"
        print(f"{name:<26}{val:<12}{p.status.value:<24}{','.join(p.provenance) or '-'}")

    if rev.build_error:
        _rule("BUILD FAILED")
        print(rev.build_error)
        return

    _rule("PREFLIGHT (advisory -- predicts, never blocks)")
    for c in rev.preflight.checks:
        print(f"  [{TICK[c.status.value]}] {c.name:<40} {c.actual or ''}")

    _rule("MEASURED VALIDATION (observed on the solid)")
    for report in rev.measured:
        for c in report.checks:
            exp = f"expected {c.expected}" if c.expected else ""
            print(f"  [{TICK[c.status.value]}] {c.name:<40} {str(c.actual or ''):<18}{exp}")
    for c in rev.cross_checks:
        print(f"  [{TICK[c.status.value]}] {c.name:<40} {c.actual or ''}")

    _rule("RELEASE GATE")
    print(rev.decision.explain())

    if rev.proposals:
        _rule("REPAIR PROPOSALS")
        for p in rev.proposals:
            mark = "RECOMMENDED" if p.recommended else ""
            print(f"  [{p.safety.value.upper():<6}] {p.id:<24}{p.title}  {mark}")
            print(f"           {p.rationale}")
            if p.consequence:
                print(f"           CONSEQUENCE: {p.consequence}")
            if not p.updates:
                print("           (no automatic change; needs a human decision first)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spec2cad")
    parser.add_argument("example_dir", type=Path,
                        help="directory holding sketch.png, motor_datasheet.pdf, requirement.txt")
    parser.add_argument("--approve", metavar="PROPOSAL_ID",
                        help="apply a repair proposal and re-evaluate")
    parser.add_argument("--approved-by", default="cli-user")
    parser.add_argument("--acknowledge-unsafe", action="store_true",
                        help="required to apply a proposal classified unsafe")
    parser.add_argument("--backend", help="force a sketch backend: openai|anthropic|fixture")
    parser.add_argument("--out", type=Path, default=Path("build"),
                        help="directory for exported artifacts")
    parser.add_argument("--script", action="store_true", help="print the generated CadQuery")
    args = parser.parse_args(argv)

    d = args.example_dir
    sketch, datasheet, requirement = (
        d / "sketch.png", d / "motor_datasheet.pdf", d / "requirement.txt"
    )
    supplied = [path for path in (sketch, datasheet, requirement) if path.exists()]
    if not supplied:
        print(
            f"no supported inputs in {d}: expected sketch.png, "
            "motor_datasheet.pdf, or requirement.txt",
            file=sys.stderr,
        )
        return 2

    result = run(
        sketch if sketch.exists() else None,
        datasheet if datasheet.exists() else None,
        requirement if requirement.exists() else None,
        args.backend,
        use_reasoning=True,
    )
    print_evidence(result)
    print_revision(result.latest)

    if args.approve:
        try:
            result = repair(
                result, args.approve,
                approved_by=args.approved_by,
                acknowledge_unsafe=args.acknowledge_unsafe,
            )
        except PermissionError as exc:
            _rule("REPAIR REFUSED")
            print(exc)
            return 3
        except (KeyError, ValueError) as exc:
            _rule("REPAIR REFUSED")
            print(exc)
            return 3
        print_revision(result.latest)

    latest = result.latest
    if args.script and latest.script:
        _rule("GENERATED CADQUERY (for review; not executed)")
        print(latest.script)

    if latest.execution is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        stl = export_stl(latest.execution, args.out / f"v{latest.revision}.stl")
        _rule("ARTIFACTS")
        print(f"  mesh  {stl}")
        if latest.released:
            step = export_step(latest.execution, args.out / f"v{latest.revision}.step")
            print(f"  STEP  {step}")
            reports = verify_exported_step(step, latest.intent, latest.intent_graph)
            ok = all(r.passed for r in reports)
            print(f"  re-imported STEP re-validated: {'PASS' if ok else 'FAIL'}")
            if not ok:
                for r in reports:
                    for c in r.failures:
                        print(f"    FAIL {c.name}: {c.message}")
                return 1
        else:
            print(f"  STEP  withheld -- {latest.decision.mesh_watermark}")

    return 0 if latest.released else 1


if __name__ == "__main__":
    raise SystemExit(main())
