"""AST policy: Rule Lab and FDD scripts are PyArrow-only (no pandas on the IoT edge)."""

from __future__ import annotations

import ast
from typing import Any

FORBIDDEN_IMPORT_ROOTS = frozenset({"pandas", "numpy"})

NO_PANDAS_AGENT_MSG = (
    "PyArrow-only Rule Lab: do not import pandas or numpy. "
    "Use pyarrow (pa) and pyarrow.compute (pc). "
    "Script mode injects `table` (pa.Table) and `cfg` — not `df` or pd.DataFrame."
)

SCRIPT_TABLE_MSG = (
    "Use `table` (PyArrow pa.Table), not `df`. "
    "The FDD script sandbox injects `table`, `cfg`, and expects an `out` dict."
)


def _issue(
    line: int,
    message: str,
    *,
    severity: str = "error",
    col: int = 1,
) -> dict[str, Any]:
    return {
        "line": line,
        "col": col,
        "end_col": col + 6,
        "message": message,
        "severity": severity,
    }


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.FunctionDef | None:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.FunctionDef):
            return current
        current = parents.get(current)
    return None


def _is_function_param(name_node: ast.Name, parents: dict[ast.AST, ast.AST]) -> bool:
    fn = _enclosing_function(name_node, parents)
    if fn is None:
        return False
    return name_node.id in {a.arg for a in fn.args.args}


def _is_module_level(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.ClassDef, ast.Lambda, ast.AsyncFunctionDef)):
            return False
        current = parents.get(current)
    return True


def lint_pyarrow_only(tree: ast.AST, *, script_mode: bool = False) -> list[dict[str, Any]]:
    """Return lint issues for pandas/DataFrame patterns forbidden on the edge."""
    issues: list[dict[str, Any]] = []
    parents = _parent_map(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "to_pandas":
            issues.append(
                _issue(
                    node.lineno or 1,
                    f"to_pandas() forbidden — {NO_PANDAS_AGENT_MSG}",
                )
            )

        if isinstance(node, ast.Attribute) and node.attr == "DataFrame":
            if isinstance(node.value, ast.Name) and node.value.id in {"pd", "pandas"}:
                issues.append(
                    _issue(
                        node.lineno or 1,
                        f"pd.DataFrame is forbidden — {NO_PANDAS_AGENT_MSG}",
                    )
                )

        if isinstance(node, ast.Name) and node.id == "df" and isinstance(node.ctx, ast.Load):
            if _is_function_param(node, parents):
                continue
            if _is_module_level(node, parents) or script_mode:
                issues.append(
                    _issue(
                        node.lineno or 1,
                        SCRIPT_TABLE_MSG if script_mode else f"`df` is not defined in Arrow rules — {SCRIPT_TABLE_MSG}",
                    )
                )
            else:
                issues.append(
                    _issue(
                        node.lineno or 1,
                        f"`df` inside rule functions is discouraged — pass/use `table` (PyArrow). {SCRIPT_TABLE_MSG}",
                        severity="warning",
                    )
                )

    return issues
