"""Server-side Python playground: lint + execute on pandas DataFrames (Open-FDD)."""

from __future__ import annotations

import ast
import builtins as _builtins
import datetime
import io
import math
import time
import traceback
from contextlib import nullcontext, redirect_stdout
from typing import Any, Callable

import pandas as pd

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    NUMPY_AVAILABLE = False

ALLOWED_IMPORT_ROOTS = frozenset(
    {"datetime", "math", "numpy", "pandas", "open_fdd", "openfdd"}
)


def lint_python(code: str) -> dict[str, Any]:
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
                            "severity": "warning",
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
                        "severity": "warning",
                    }
                )
    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}


def _restricted_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: Any = (),
    level: int = 0,
) -> Any:
    root = name.split(".")[0]
    if root not in ALLOWED_IMPORT_ROOTS:
        allowed = ", ".join(sorted(ALLOWED_IMPORT_ROOTS))
        raise ImportError(f"import of '{name}' not allowed (allowed: {allowed})")
    return _builtins.__import__(name, globals, locals, fromlist, level)


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


def _rule_sandbox() -> dict[str, Any]:
    g: dict[str, Any] = {"__builtins__": _sandbox_builtins()}
    g["datetime"] = datetime
    g["math"] = math
    if NUMPY_AVAILABLE:
        g["np"] = np
        g["numpy"] = np
    g["pd"] = pd
    g["pandas"] = pd
    return g


def compile_evaluate(code: str) -> Callable[..., Any]:
    g = _rule_sandbox()
    exec(code, g, g)  # noqa: S102 — intentional sandboxed user code
    fn = g.get("evaluate")
    if not callable(fn):
        raise ValueError("rule code must define evaluate(row, cfg, prev_row=None, rows=None)")
    return fn


def sweep_rule(
    code: str,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    capture_print: bool = True,
) -> tuple[list[bool], list[dict[str, Any]]]:
    evaluate = compile_evaluate(code)
    flags: list[bool] = []
    events: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    buf = io.StringIO()
    flagged = 0
    for index, row in enumerate(rows):
        try:
            ctx = redirect_stdout(buf) if capture_print else nullcontext()
            with ctx:
                fault = bool(evaluate(row, cfg, prev_row=prev, rows=rows))
        except Exception as exc:
            events.append(
                {
                    "type": "row",
                    "row": index,
                    "status": "error",
                    "message": str(exc),
                }
            )
            flags.append(False)
            prev = row
            continue
        flags.append(fault)
        if fault:
            flagged += 1
        events.append(
            {
                "type": "row",
                "row": index,
                "status": "fault" if fault else "ok",
                "ts": row.get("timestamp") or row.get("ts"),
            }
        )
        prev = row
    text = buf.getvalue().strip()
    if text:
        events.insert(0, {"type": "stdout", "text": text})
    events.append(
        {
            "type": "summary",
            "rows": len(rows),
            "flagged": flagged,
            "sweep_mode": "per_row",
        }
    )
    return flags, events


def run_dataframe_script(
    code: str,
    df: pd.DataFrame,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute user script with `df`, optional `cfg`, must leave `out` dict."""
    g = _rule_sandbox()
    g["df"] = df.copy()
    g["cfg"] = cfg or {}
    g["out"] = {"df": g["df"], "events": []}
    stdout = io.StringIO()
    started = time.time()
    try:
        with redirect_stdout(stdout):
            exec(code, g, g)  # noqa: S102
    except Exception:
        return {
            "ok": False,
            "error": traceback.format_exc(limit=8),
            "stdout": stdout.getvalue(),
            "ms": int((time.time() - started) * 1000),
        }
    out = g.get("out")
    if not isinstance(out, dict):
        out = {"df": g.get("df", df), "events": [{"type": "note", "text": "no out dict; using df"}]}
    result_df = out.get("df")
    if not isinstance(result_df, pd.DataFrame):
        result_df = g.get("df", df)
    preview = result_df.head(50).to_dict(orient="records")
    flag_cols = [c for c in result_df.columns if str(c).endswith("_flag")]
    return {
        "ok": True,
        "stdout": stdout.getvalue(),
        "ms": int((time.time() - started) * 1000),
        "rows": len(result_df),
        "columns": list(result_df.columns),
        "flag_columns": flag_cols,
        "preview": preview,
        "events": out.get("events") or [],
    }


def dataframe_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df
