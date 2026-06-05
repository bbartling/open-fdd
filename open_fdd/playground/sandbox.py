"""Lint, compile, and sweep ``evaluate(row, cfg, …)`` rules — edge, PyPI, and AWS lambda parity."""

from __future__ import annotations

import ast
import builtins as _builtins
import datetime
import io
import math
import time
import traceback
from collections.abc import Mapping
from contextlib import nullcontext, redirect_stdout
from typing import Any, Callable

from open_fdd.playground.cookbook import attach_rolling_avg, inject_cookbook_helpers, normalize_rolling_avg_minutes

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    NUMPY_AVAILABLE = False

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore
    PANDAS_AVAILABLE = False

ALLOWED_IMPORT_ROOTS = frozenset(
    {"datetime", "math", "numpy", "pandas", "open_fdd", "openfdd"}
)

DEFAULT_ROW_TIMEOUT_S = 2.0
DEFAULT_EXEC_TIMEOUT_S = 30.0
MAX_STDOUT_CHARS = 8000


def lint_python(
    code: str,
    *,
    require_evaluate: bool = True,
    strict_imports: bool = False,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not code.strip():
        return {"ok": True, "issues": issues}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        line = exc.lineno or 1
        col = exc.offset or 1
        issues.append(
            {
                "line": line,
                "col": col,
                "end_col": col + 1,
                "message": exc.msg or "invalid syntax",
                "severity": "error",
            }
        )
        return {"ok": False, "issues": issues}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    issues.append(
                        {
                            "line": node.lineno,
                            "col": node.col_offset or 1,
                            "end_col": (node.col_offset or 1) + 6,
                            "message": f"import '{alias.name}' not allowed",
                            "severity": "error" if strict_imports else "warning",
                        }
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                issues.append(
                    {
                        "line": node.lineno,
                        "col": node.col_offset or 1,
                        "end_col": (node.col_offset or 1) + 6,
                        "message": f"import from '{node.module}' not allowed",
                        "severity": "error" if strict_imports else "warning",
                    }
                )

    has_evaluate = any(
        isinstance(node, ast.FunctionDef) and node.name == "evaluate" for node in ast.iter_child_nodes(tree)
    )
    if require_evaluate and not has_evaluate:
        issues.append(
            {
                "line": 1,
                "col": 1,
                "end_col": 1,
                "message": "rule must define evaluate(row, cfg, prev_row=None, rows=None)",
                "severity": "error",
            }
        )

    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}


def _restricted_import(
    name: str,
    _globals: Any = None,
    _locals: Any = None,
    fromlist: Any = (),
    level: int = 0,
) -> Any:
    root = name.split(".")[0]
    if root not in ALLOWED_IMPORT_ROOTS:
        allowed = ", ".join(sorted(ALLOWED_IMPORT_ROOTS))
        raise ImportError(f"import of '{name}' not allowed (allowed: {allowed})")
    return _builtins.__import__(name, _globals, _locals, fromlist, level)


def _sandbox_builtins() -> dict[str, Any]:
    return {
        "print": print,
        "range": range,
        "len": len,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "round": round,
        "float": float,
        "int": int,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "enumerate": enumerate,
        "zip": zip,
        "sorted": sorted,
        "any": any,
        "all": all,
        "isinstance": isinstance,
        "__import__": _restricted_import,
    }


def rule_globals() -> dict[str, Any]:
    """Sandbox namespace for ``exec()`` — cookbook helpers + optional numpy/pandas."""
    g: dict[str, Any] = {"__builtins__": _sandbox_builtins()}
    g["datetime"] = datetime
    g["math"] = math
    if NUMPY_AVAILABLE:
        g["np"] = np
        g["numpy"] = np
    if PANDAS_AVAILABLE:
        g["pd"] = pd
        g["pandas"] = pd
    inject_cookbook_helpers(g)
    return g


def compile_evaluate(code: str) -> Callable[..., Any]:
    lint = lint_python(code, strict_imports=True)
    if not lint["ok"]:
        lines = [
            f"line {issue.get('line', '?')}: {issue['message']}"
            for issue in lint.get("issues", [])
            if issue.get("severity") == "error"
        ]
        raise ValueError("syntax error — fix before run\n" + "\n".join(lines))
    g = rule_globals()
    try:
        compiled = compile(code, "<rule>", "exec")
        exec(compiled, g, g)  # noqa: S102 — intentional sandboxed user code
    except (SyntaxError, IndentationError, TabError) as exc:
        line = getattr(exc, "lineno", None) or "?"
        raise ValueError(f"{exc.__class__.__name__} at line {line}: {exc.msg or exc}") from exc
    fn = g.get("evaluate")
    if not callable(fn):
        raise ValueError("rule code must define evaluate(row, cfg, prev_row=None, rows=None)")
    return fn


def parse_evaluate_result(raw: Any, rows: list[dict[str, Any]]) -> tuple[bool, list[int]]:
    if isinstance(raw, tuple) and len(raw) >= 1:
        hit = bool(raw[0])
        if hit and len(raw) >= 2 and raw[1] is not None:
            window = raw[1]
            indices: list[int] = []
            if isinstance(window, list):
                for item in window:
                    if isinstance(item, dict) and "row" in item:
                        indices.append(int(item["row"]))
                    elif isinstance(item, int):
                        indices.append(item)
            return hit, indices
        return hit, []
    return bool(raw), []


class _CappedStdout(io.StringIO):
    def write(self, s: str) -> int:  # type: ignore[override]
        cur = self.getvalue()
        if len(cur) >= MAX_STDOUT_CHARS:
            return 0
        room = MAX_STDOUT_CHARS - len(cur)
        chunk = s[:room]
        return super().write(chunk)


def sweep_rule(
    code: str,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    capture_print: bool = True,
    rolling_avg_minutes: int | None = None,
    series_ctx: dict[str, Any] | None = None,
    exec_timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
    row_timeout_s: float = DEFAULT_ROW_TIMEOUT_S,
) -> tuple[list[bool], list[dict[str, Any]]]:
    """Run ``evaluate`` on each row; return per-row flags and diagnostic events."""
    if rows:
        minutes = normalize_rolling_avg_minutes(
            rolling_avg_minutes
            if rolling_avg_minutes is not None
            else cfg.get("rolling_avg_minutes", 5)
        )
        explicit_window = rolling_avg_minutes is not None or cfg.get("rolling_avg_minutes") is not None
        missing_avg = "temp_rolling_avg" not in rows[0]
        stale_window = rows[0].get("rolling_avg_minutes") != minutes
        if series_ctx is not None or missing_avg or (explicit_window and stale_window):
            attach_rolling_avg(rows, minutes=minutes)
    lint = lint_python(code, strict_imports=True)
    if not lint["ok"]:
        lines = [
            f"line {issue.get('line', '?')}, col {issue.get('col', '?')}: {issue['message']}"
            for issue in lint.get("issues", [])
            if issue.get("severity") == "error"
        ]
        text = "syntax error — fix before run\n" + "\n".join(lines) if lines else "syntax error — fix before run"
        return [False] * len(rows), [{"type": "error", "text": text}]
    try:
        evaluate = compile_evaluate(code)
    except ValueError as exc:
        return [False] * len(rows), [
            {"type": "error", "text": str(exc), "trace": traceback.format_exc(limit=8)}
        ]

    flags: list[bool] = [False] * len(rows)
    events: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    buf: io.StringIO = _CappedStdout() if capture_print else io.StringIO()
    deadline = time.time() + exec_timeout_s

    for index, row in enumerate(rows):
        if time.time() >= deadline:
            events.append({"type": "error", "text": "rule execution timed out (total budget exceeded)"})
            break

        def _eval_row() -> Any:
            ctx = redirect_stdout(buf) if capture_print else nullcontext()
            with ctx:
                if series_ctx is not None:
                    try:
                        return evaluate(row, cfg, prev_row=prev, rows=rows, series=series_ctx)
                    except TypeError:
                        return evaluate(row, cfg, prev_row=prev, rows=rows)
                return evaluate(row, cfg, prev_row=prev, rows=rows)

        try:
            raw = _eval_row()
            instant, paint = parse_evaluate_result(raw, rows)
        except Exception as exc:  # noqa: BLE001 — user rule code
            events.append(
                {
                    "type": "row",
                    "row": index,
                    "status": "error",
                    "message": str(exc)[:500],
                }
            )
            prev = row
            continue

        flags[index] = instant
        for paint_idx in paint:
            if 0 <= paint_idx < len(flags):
                flags[paint_idx] = True
        if instant:
            events.append({"type": "row", "row": index, "status": "hit"})
        prev = row

    if capture_print and buf.getvalue().strip():
        events.append({"type": "stdout", "text": buf.getvalue()[:MAX_STDOUT_CHARS]})

    return flags, events


def coerce_event_item(event: Any) -> dict[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    return {"_invalid_event": True, "raw": str(event)[:500]}
