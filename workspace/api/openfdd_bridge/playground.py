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

GO_LIVE_BATCH_HOURS = 6
GO_LIVE_MAX_LOOKBACK_HOURS = 168
GO_LIVE_OVERLAP_MINUTES = 15


def _lint_error_events(lint: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [
        f"line {issue.get('line', '?')}, col {issue.get('col', '?')}: {issue['message']}"
        for issue in lint.get("issues", [])
        if issue.get("severity") == "error"
    ]
    text = "syntax error — fix before run\n" + "\n".join(lines) if lines else "syntax error — fix before run"
    return [{"type": "error", "text": text}]


def lint_python(code: str, *, require_evaluate: bool = True) -> dict[str, Any]:
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


from .fdd_row_prep import inject_rule_helpers


def _parse_evaluate_result(raw: Any, rows: list[dict[str, Any]]) -> tuple[bool, list[int]]:
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


def _rule_sandbox() -> dict[str, Any]:
    g: dict[str, Any] = {"__builtins__": _sandbox_builtins()}
    g["datetime"] = datetime
    g["math"] = math
    if NUMPY_AVAILABLE:
        g["np"] = np
        g["numpy"] = np
    g["pd"] = pd
    g["pandas"] = pd
    inject_rule_helpers(g)
    return g


def compile_evaluate(code: str) -> Callable[..., Any]:
    lint = lint_python(code)
    if not lint["ok"]:
        lines = [
            f"line {issue.get('line', '?')}: {issue['message']}"
            for issue in lint.get("issues", [])
            if issue.get("severity") == "error"
        ]
        raise ValueError("syntax error — fix before run\n" + "\n".join(lines))
    g = _rule_sandbox()
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


def sweep_rule(
    code: str,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    capture_print: bool = True,
) -> tuple[list[bool], list[dict[str, Any]]]:
    lint = lint_python(code)
    if not lint["ok"]:
        return [False] * len(rows), _lint_error_events(lint)
    try:
        evaluate = compile_evaluate(code)
    except ValueError as exc:
        return [False] * len(rows), [
            {"type": "error", "text": str(exc), "trace": traceback.format_exc(limit=8)},
        ]
    flags: list[bool] = [False] * len(rows)
    events: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    buf = io.StringIO()
    for index, row in enumerate(rows):
        try:
            ctx = redirect_stdout(buf) if capture_print else nullcontext()
            with ctx:
                raw = evaluate(row, cfg, prev_row=prev, rows=rows)
            instant, paint = _parse_evaluate_result(raw, rows)
        except Exception as exc:
            events.append(
                {
                    "type": "row",
                    "row": index,
                    "status": "error",
                    "message": str(exc),
                }
            )
            prev = row
            continue
        if instant:
            flags[index] = True
        for idx in paint:
            if 0 <= idx < len(flags):
                flags[idx] = True
        row_fault = flags[index]
        events.append(
            {
                "type": "row",
                "row": index,
                "status": "fault" if row_fault else "ok",
                "ts": row.get("timestamp") or row.get("ts"),
            }
        )
        prev = row
    flagged = sum(flags)
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
    metrics = out.get("metrics") if isinstance(out.get("metrics"), dict) else {}
    return {
        "ok": True,
        "stdout": stdout.getvalue(),
        "ms": int((time.time() - started) * 1000),
        "rows": len(result_df),
        "columns": list(result_df.columns),
        "flag_columns": flag_cols,
        "preview": preview,
        "events": out.get("events") or [],
        "metrics": metrics,
    }


def sweep_dataframe_chunked(
    code: str,
    cfg: dict[str, Any],
    df: pd.DataFrame,
    *,
    chunk_hours: float = GO_LIVE_BATCH_HOURS,
    overlap_minutes: int = GO_LIVE_OVERLAP_MINUTES,
    enrich_rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Evaluate a rule on a large frame in time chunks (bounded memory)."""
    from .data_loader import rows_for_evaluate

    if df.empty:
        return 0, 0, [{"type": "summary", "rows": 0, "flagged": 0, "sweep_mode": "chunked"}]

    if "timestamp" not in df.columns:
        rows = rows_for_evaluate(df, limit=len(df))
        if enrich_rows:
            rows = enrich_rows(rows)
        flags, events = sweep_rule(code, cfg, rows, capture_print=False)
        return len(rows), sum(flags), events

    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    work = df.copy()
    work["_ts_ms"] = ts.astype("int64") // 1_000_000
    work = work.dropna(subset=["_ts_ms"]).sort_values("_ts_ms").reset_index(drop=True)
    if work.empty:
        return 0, 0, [{"type": "summary", "rows": 0, "flagged": 0, "sweep_mode": "chunked"}]

    start_ms = int(work["_ts_ms"].min())
    end_ms = int(work["_ts_ms"].max())
    chunk_ms = max(1, int(float(chunk_hours) * 3600 * 1000))
    overlap_ms = max(int(overlap_minutes * 60_000), 10 * 60_000)

    merged = [False] * len(work)
    events: list[dict[str, Any]] = []
    cursor = start_ms
    chunk_num = 0

    while cursor <= end_ms:
        chunk_end = min(cursor + chunk_ms, end_ms + 1)
        fetch_start = max(start_ms, cursor - overlap_ms) if cursor > start_ms else cursor
        mask = (work["_ts_ms"] >= fetch_start) & (work["_ts_ms"] < chunk_end)
        pos_indices = [i for i, hit in enumerate(mask) if hit]
        chunk_df = work.loc[mask].drop(columns=["_ts_ms"])
        if not chunk_df.empty:
            rows = rows_for_evaluate(chunk_df, limit=len(chunk_df))
            if enrich_rows:
                rows = enrich_rows(rows)
            flags, chunk_events = sweep_rule(code, cfg, rows, capture_print=False)
            for k, flagged in enumerate(flags):
                if flagged and k < len(pos_indices):
                    merged[pos_indices[k]] = True
            events.append(
                {
                    "type": "stdout",
                    "text": f"chunk {chunk_num + 1}: rows={len(rows)} flagged={sum(flags)}",
                }
            )
            if any(e.get("type") == "error" for e in chunk_events):
                events.extend(chunk_events)
                break
        cursor = chunk_end
        chunk_num += 1

    flagged = sum(merged)
    events.append(
        {
            "type": "summary",
            "rows": len(work),
            "flagged": flagged,
            "sweep_mode": "chunked",
            "chunk_count": chunk_num,
        }
    )
    return len(work), flagged, events


def dataframe_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df
