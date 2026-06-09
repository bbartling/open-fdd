"""CI guard: arrow_runtime and faults packages must not import pandas."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGE_PACKAGES = [
    ROOT / "open_fdd" / "arrow_runtime",
    ROOT / "open_fdd" / "faults",
]


def _imports_pandas(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "pandas" for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "pandas":
            return True
    return False


def test_edge_packages_have_no_pandas_imports():
    violations: list[str] = []
    for pkg in EDGE_PACKAGES:
        for py in pkg.rglob("*.py"):
            if _imports_pandas(py):
                violations.append(str(py.relative_to(ROOT)))
    assert not violations, f"pandas found in edge FDD paths: {violations}"
