from pathlib import Path

from eval.public_guardrails import run_suite, write_reports


def main() -> int:
    outcomes = run_suite()
    root = Path(__file__).resolve().parent
    write_reports(outcomes, root)
    passed = sum(item.passed for item in outcomes)
    print(f"public guardrails: {passed}/{len(outcomes)} passed")
    return 0 if passed == len(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
