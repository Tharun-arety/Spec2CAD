"""CLI entry point for the adversarial generalization suite."""

from __future__ import annotations

import sys
from pathlib import Path

from eval.adversarial_generalization import Metric, run_suite, write_reports

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_REPORT = ROOT / "eval" / "adversarial_generalization_report.md"
JSON_REPORT = ROOT / "eval" / "adversarial_generalization_report.json"


def main() -> int:
    report = run_suite()
    write_reports(report, MARKDOWN_REPORT, JSON_REPORT)
    for metric in Metric:
        summary = report.summary_for(metric)
        print(
            f"{summary.metric}: {summary.passed}/{summary.total} "
            f"({summary.rate:.0%})"
        )
    print(f"correct refusals: {report.correct_refusals}")
    print(f"wrote {MARKDOWN_REPORT.relative_to(ROOT)}")
    print(f"wrote {JSON_REPORT.relative_to(ROOT)}")
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
