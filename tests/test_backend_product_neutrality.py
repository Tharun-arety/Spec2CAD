"""Backend product code must interpret contracts, not recognize demo nouns."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ROOT / "spec2cad" / "backends"
FORBIDDEN_PRODUCT_TERMS = (
    "plate_width",
    "plate_height",
    "plate_thickness",
    "shaft_opening",
    "mounting_hole",
    "hole_spacing",
    "motor_adapter",
    "motor adapter",
)


def test_backend_implementations_have_no_demo_specific_identifiers():
    violations = []
    for path in sorted(BACKENDS.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_PRODUCT_TERMS:
            if term in source:
                violations.append(f"{path.name}: {term}")
    assert not violations, "backend product special cases found: " + ", ".join(violations)
