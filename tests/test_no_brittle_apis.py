"""Guard tests: keep the validation layer off fragile foundations.

Each ban below corresponds to something that actually misbehaved during
development, so these are regression guards rather than style rules. They are
enforced by scanning the source because the failure mode is someone reaching for
the convenient-but-wrong call again later, which no runtime test would catch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

VALIDATION_DIR = Path(__file__).resolve().parents[1] / "spec2cad" / "validation"

BANS = [
    (
        r"_geomAdaptor",
        "private OCC accessor; the public Edge.radius() returns the same value",
    ),
    (
        r"\bBoundingBox\b",
        "OCC bounding boxes carry a tolerance gap -- BoundingBox().zlen reported "
        "5.007 for a 5.000 mm plate. Measure from planar face positions instead",
    ),
    (
        r"\.wrapped\b",
        "reaching through the CadQuery wrapper into raw OCC",
    ),
]


def _sources() -> list[Path]:
    return sorted(p for p in VALIDATION_DIR.rglob("*.py") if p.name != "__init__.py")


def _strip_comments_and_docstrings(text: str) -> str:
    """Remove docstrings and comments so prose explaining a ban is not itself a hit."""
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    text = re.sub(r"'''(?:.|\n)*?'''", "", text)
    return re.sub(r"#[^\n]*", "", text)


@pytest.mark.parametrize("pattern,reason", BANS)
def test_validation_layer_avoids_fragile_apis(pattern, reason):
    offenders = []
    for path in _sources():
        code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), start=1):
            if re.search(pattern, line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, f"{reason}\n" + "\n".join(offenders)


def test_validation_layer_does_not_assert_exact_face_counts():
    """Exact face-type censuses break on any added fillet and prove little.

    Material integrity is checked by comparing measured volume to the analytic
    model, which is tolerance-aware and catches real defects.
    """
    suspicious = re.compile(
        r"len\(\s*\w+\.Faces\(\)\s*\)\s*==|"
        r"(?:PLANE|CYLINDER)['\"]\s*\]\s*==\s*\d+"
    )
    offenders = []
    for path in _sources():
        code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), start=1):
            if suspicious.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "exact face-count assertion found:\n" + "\n".join(offenders)


def test_only_the_kernel_facade_imports_cadquery():
    """Keeping kernel imports contained is what makes the IR portable."""
    root = Path(__file__).resolve().parents[1] / "spec2cad"
    allowed = {Path("backends/cadquery_kernel.py")}
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root) in allowed:
            continue
        code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
        if re.search(r"^\s*(?:import|from)\s+cadquery", code, re.MULTILINE):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, (
        "cadquery imported outside the CAD layer: " + ", ".join(offenders)
    )


def test_no_module_executes_model_generated_python():
    """The model emits schema-validated data, never code."""
    root = Path(__file__).resolve().parents[1] / "spec2cad"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        code = _strip_comments_and_docstrings(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), start=1):
            if re.search(r"\b(?:eval|exec|compile)\s*\(", line):
                offenders.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    assert not offenders, "dynamic code execution found:\n" + "\n".join(offenders)
