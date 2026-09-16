"""The third-party CAD kernel cannot leak beyond its one import facade."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "spec2cad"
ALLOWED = Path("backends/cadquery_kernel.py")


def cadquery_imports(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            name.name == "cadquery" or name.name.startswith("cadquery.")
            for name in node.names
        ):
            lines.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and (
            node.module == "cadquery" or (node.module or "").startswith("cadquery.")
        ):
            lines.append(node.lineno)
    return lines


def test_only_kernel_facade_imports_cadquery_package():
    found = {
        path.relative_to(PACKAGE): cadquery_imports(path)
        for path in PACKAGE.rglob("*.py")
        if cadquery_imports(path)
    }
    assert found == {ALLOWED: [7]}
