"""Server-side Python playground: lint + execute Arrow rules and scripts (Open-FDD)."""

from __future__ import annotations

import datetime
import io
import math
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import nullcontext, redirect_stdout
from collections.abc import Mapping
from typing import Any, Callable

import pandas as pd

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    NUMPY_AVAILABLE = False

from open_fdd.playground.sandbox import (
    compile_evaluate,
    lint_python,
    parse_evaluate_result as _parse_evaluate_result,
    rule_globals as _rule_sandbox,
)

GO_LIVE_BATCH_HOURS = 6
GO_LIVE_MAX_LOOKBACK_HOURS = 168
GO_LIVE_OVERLAP_MINUTES = 15

MAX_STDOUT_CHARS = 8000
MAX_PUBLIC_TRACE_CHARS = 500
_ROW_TIMEOUT_S = 2.0


def _exec_timeout_s() -> float:
    try:
        return max(1.0, float(os.environ.get("OFDD_PLAYGROUND_TIMEOUT_S", "30")))
    except ValueError:
        return 30.0


def _cap_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n… (truncated)"


def sanitize_traceback_text(text: str | None) -> str | None:
    if not text:
        return None
    from .security import debug_tracebacks_enabled

    if debug_tracebacks_enabled():
        return _cap_text(text, MAX_STDOUT_CHARS)
    first_line = text.strip().splitlines()[0] if text.strip() else "execution failed"
    return _cap_text(first_line, MAX_PUBLIC_TRACE_CHARS)


def _coerce_event_item(event: Any) -> dict[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    return {"_invalid_event": True, "raw": str(event)[:MAX_PUBLIC_TRACE_CHARS]}


def sanitize_events(events: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        item = _coerce_event_item(event)
        if "trace" in item:
            item["trace"] = sanitize_traceback_text(str(item.get("trace") or ""))
        if item.get("type") == "stdout" and isinstance(item.get("text"), str):
            item["text"] = _cap_text(item["text"], MAX_STDOUT_CHARS)
        out.append(item)
    return out


class _CappedStdout(io.StringIO):
    def write(self, s: str) -> int:  # type: ignore[override]
        cur = self.getvalue()
        if len(cur) >= MAX_STDOUT_CHARS:
            return 0
        room = MAX_STDOUT_CHARS - len(cur)
        chunk = s[:room]
        return super().write(chunk)


def _call_with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    executor = ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(fn)
    try:
        return fut.result(timeout=timeout_s)
    except FuturesTimeout:
        fut.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _lint_error_events(lint: dict[str, Any]) -> list[dict[str, Any]]:
    lines = [
        f"line {issue.get('line', '?')}, col {issue.get('col', '?')}: {issue['message']}"
        for issue in lint.get("issues", [])
        if issue.get("severity") == "error"
    ]
    text = "syntax error — fix before run\n" + "\n".join(lines) if lines else "syntax error — fix before run"
    return [{"type": "error", "text": text}]


def sweep_rule(
    code: str,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    capture_print: bool = True,
) -> tuple[list[bool], list[dict[str, Any]]]:
    from .playground_exec import run_pickled_job, subprocess_enabled

    if subprocess_enabled():
        payload = run_pickled_job(
            {
                "op": "sweep_rule",
                "code": code,
                "cfg": cfg,
                "rows": rows,
                "capture_print": capture_print,
            },
            timeout_s=_exec_timeout_s(),
        )
        if not payload.get("ok"):
            err = payload.get("error") or "rule execution failed"
            if payload.get("timed_out"):
                err = "rule execution timed out (total budget exceeded)"
            return [False] * len(rows), sanitize_events([{"type": "error", "text": err}])
        return payload["flags"], payload["events"]
    return _sweep_rule_impl(code, cfg, rows, capture_print=capture_print)


def _sweep_rule_impl(
    code: str,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    capture_print: bool = True,
) -> tuple[list[bool], list[dict[str, Any]]]:
    lint = lint_python(code, strict_imports=True)
    if not lint["ok"]:
        return [False] * len(rows), sanitize_events(_lint_error_events(lint))
    try:
        evaluate = compile_evaluate(code)
    except ValueError as exc:
        return [False] * len(rows), sanitize_events(
            [{"type": "error", "text": str(exc), "trace": traceback.format_exc(limit=8)}]
        )
    flags: list[bool] = [False] * len(rows)
    events: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    buf: io.StringIO = _CappedStdout() if capture_print else io.StringIO()
    deadline = time.time() + _exec_timeout_s()
    for index, row in enumerate(rows):
        if time.time() >= deadline:
            events.append({"type": "error", "text": "rule execution timed out (total budget exceeded)"})
            break
        remaining = max(0.1, min(_ROW_TIMEOUT_S, deadline - time.time()))

        def _eval_row() -> Any:
            ctx = redirect_stdout(buf) if capture_print else nullcontext()
            with ctx:
                return evaluate(row, cfg, prev_row=prev, rows=rows)

        try:
            raw = _call_with_timeout(_eval_row, remaining)
            instant, paint = _parse_evaluate_result(raw, rows)
        except FuturesTimeout:
            events.append(
                {
                    "type": "row",
                    "row": index,
                    "status": "error",
                    "message": "row evaluation timed out",
                }
            )
            break
        except Exception as exc:
            events.append(
                {
                    "type": "row",
                    "row": index,
                    "status": "error",
                    "message": str(exc)[:MAX_PUBLIC_TRACE_CHARS],
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
        events.insert(0, {"type": "stdout", "text": _cap_text(text, MAX_STDOUT_CHARS)})
    events.append(
        {
            "type": "summary",
            "rows": len(rows),
            "flagged": flagged,
            "sweep_mode": "per_row",
        }
    )
    return flags, sanitize_events(events)


def run_dataframe_script(
    code: str,
    df: pd.DataFrame,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute user script with `df`, optional `cfg`, must leave `out` dict."""
    lint = lint_python(code, require_evaluate=False, strict_imports=True)
    if not lint["ok"]:
        return {
            "ok": False,
            "error": "disallowed import or syntax error",
            "issues": lint.get("issues"),
            "events": _lint_error_events(lint),
        }

    from .playground_exec import run_pickled_job, subprocess_enabled

    if subprocess_enabled():
        started = time.time()
        payload = run_pickled_job(
            {
                "op": "run_script",
                "code": code,
                "df": df,
                "cfg": cfg or {},
            },
            timeout_s=_exec_timeout_s(),
        )
        if not payload.get("ok"):
            err = payload.get("error") or "script failed"
            stderr = (payload.get("worker_stderr") or "").strip()
            if stderr:
                err = f"{err}: {stderr[:400]}"
            if payload.get("timed_out"):
                err = "script execution timed out"
            return {
                "ok": False,
                "error": err,
                "stdout": "",
                "ms": int((time.time() - started) * 1000),
            }
        return payload["result"]

    return _run_dataframe_script_impl(code, df, cfg=cfg)


def run_arrow_script(
    code: str,
    table: Any,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute user script with PyArrow ``table``, optional ``cfg``, must set ``out`` dict."""
    lint = lint_python(code, require_arrow_rule=False, strict_imports=True)
    if not lint["ok"]:
        return {
            "ok": False,
            "error": "disallowed import or syntax error",
            "issues": lint.get("issues"),
            "events": _lint_error_events(lint),
        }

    started = time.time()

    def _run() -> dict[str, Any]:
        g = _rule_sandbox()
        g["table"] = table
        g["cfg"] = cfg or {}
        g["out"] = {"events": []}
        stdout = _CappedStdout()
        with redirect_stdout(stdout):
            exec(code, g, g)  # noqa: S102  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
        out = g.get("out")
        if not isinstance(out, dict):
            out = {"events": [{"type": "note", "text": "no out dict from script"}]}
        return {"ok": True, "stdout": stdout.getvalue(), "out": out}

    try:
        inner = _call_with_timeout(_run, _exec_timeout_s())
    except FuturesTimeout:
        return {
            "ok": False,
            "error": "script execution timed out",
            "stdout": "",
            "ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        err = sanitize_traceback_text(str(exc)) or "script failed"
        if "df" in err and "not defined" in err:
            err = (
                f"{err} — script mode injects PyArrow `table`, not `df`. "
                "Use pyarrow.compute (pc); see docs/developer/arrow-native-runtime.md"
            )
        return {
            "ok": False,
            "error": err,
            "trace": sanitize_traceback_text(traceback.format_exc(limit=8)),
            "stdout": "",
            "ms": int((time.time() - started) * 1000),
        }
    out = inner["out"]
    metrics = out.get("metrics") if isinstance(out.get("metrics"), dict) else {}
    rows = int(getattr(table, "num_rows", 0) or 0)
    return {
        "ok": True,
        "stdout": _cap_text(str(inner.get("stdout") or ""), MAX_STDOUT_CHARS),
        "ms": int((time.time() - started) * 1000),
        "rows": rows,
        "flag_columns": [],
        "preview": [],
        "events": sanitize_events(out.get("events") or []),
        "metrics": metrics,
        "backend": "arrow",
    }


def _run_dataframe_script_impl(
    code: str,
    df: pd.DataFrame,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        g = _rule_sandbox()
        g["df"] = df.copy()
        g["cfg"] = cfg or {}
        g["out"] = {"df": g["df"], "events": []}
        stdout = _CappedStdout()
        with redirect_stdout(stdout):
            exec(code, g, g)  # noqa: S102  # nosemgrep: python.lang.security.audit.exec-detected.exec-detected
        out = g.get("out")
        if not isinstance(out, dict):
            out = {"df": g.get("df", df), "events": [{"type": "note", "text": "no out dict; using df"}]}
        result_df = out.get("df")
        if not isinstance(result_df, pd.DataFrame):
            result_df = g.get("df", df)
        return {
            "ok": True,
            "stdout": stdout.getvalue(),
            "df": result_df,
            "out": out,
        }

    started = time.time()
    try:
        inner = _call_with_timeout(_run, _exec_timeout_s())
    except FuturesTimeout:
        return {
            "ok": False,
            "error": "script execution timed out",
            "stdout": "",
            "ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": sanitize_traceback_text(str(exc)) or "script failed",
            "trace": sanitize_traceback_text(traceback.format_exc(limit=8)),
            "stdout": "",
            "ms": int((time.time() - started) * 1000),
        }
    result_df = inner["df"]
    out = inner["out"]
    preview = result_df.head(50).to_dict(orient="records")
    flag_cols = [c for c in result_df.columns if str(c).endswith("_flag")]
    metrics = out.get("metrics") if isinstance(out.get("metrics"), dict) else {}
    return {
        "ok": True,
        "stdout": _cap_text(str(inner.get("stdout") or ""), MAX_STDOUT_CHARS),
        "ms": int((time.time() - started) * 1000),
        "rows": len(result_df),
        "columns": list(result_df.columns),
        "flag_columns": flag_cols,
        "preview": preview,
        "events": sanitize_events(out.get("events") or []),
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
            flags, chunk_events = _sweep_rule_impl(code, cfg, rows, capture_print=False)
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


def lint_arrow_python(code: str) -> dict[str, Any]:
    from open_fdd.arrow_runtime.backend import lint_arrow_rule

    return lint_arrow_rule(code, strict_imports=True)


def _run_arrow_table_impl(
    code: str,
    table: Any,
    cfg: dict[str, Any] | None = None,
    *,
    rule_id: str = "",
    site_id: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    """Execute Arrow-native rule in-process (also used by playground_worker)."""
    import pyarrow as pa

    from open_fdd.arrow_runtime.backend import run_arrow_rule, run_arrow_rule_chunked
    from open_fdd.arrow_runtime.config import get_arrow_runtime_config
    from open_fdd.arrow_runtime.rules import detect_rule_backend, legacy_row_allowed, migrate_legacy_threshold_hint

    started = time.time()
    backend = detect_rule_backend(code, {"backend": cfg.get("backend") if cfg else None})
    if backend == "legacy_row" and not legacy_row_allowed({"backend": "legacy_row"}):
        hint = migrate_legacy_threshold_hint(code, cfg or {})
        return {
            "ok": False,
            "backend": "legacy_row",
            "error": "legacy row rules require backend=legacy_row or OPEN_FDD_FDD_BACKEND=legacy_row",
            "migration_hint": hint,
            "migration_message": (
                "This is a legacy row rule. Convert it to apply_faults_arrow(table, cfg, context=None) "
                "for the Arrow-native runtime."
            ),
            "ms": int((time.time() - started) * 1000),
        }
    if not isinstance(table, pa.Table):
        table = pa.Table.from_pandas(table)
    if limit and table.num_rows > limit:
        table = table.slice(table.num_rows - limit, limit)
    rt = get_arrow_runtime_config()
    if table.num_rows > rt.batch_rows:
        result = run_arrow_rule_chunked(code, table, cfg or {}, rule_id=rule_id)
    else:
        result = run_arrow_rule(code, table, cfg or {}, rule_id=rule_id)
    payload = result.as_dict()
    payload["ok"] = not result.errors
    payload["site_id"] = site_id
    payload["batch_count"] = max(1, (table.num_rows + rt.batch_rows - 1) // rt.batch_rows)
    payload["arrow_runtime"] = rt.as_dict()
    payload["ms"] = int((time.time() - started) * 1000)
    if result.errors:
        payload["error"] = result.errors[0]
        payload["events"] = sanitize_events([{"type": "error", "text": result.errors[0]}])
    else:
        payload["flagged"] = result.true_count
        payload["rows"] = result.row_count
        payload["events"] = sanitize_events(
            [
                {
                    "type": "summary",
                    "rows": result.row_count,
                    "flagged": result.true_count,
                    "sweep_mode": "arrow",
                    "duration_ms": result.duration_ms,
                }
            ]
        )
    return payload


def run_arrow_table(
    code: str,
    table: Any,
    cfg: dict[str, Any] | None = None,
    *,
    rule_id: str = "",
    site_id: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    """Execute Arrow-native rule against a PyArrow Table; JSON-safe response."""
    from .playground_exec import run_pickled_job, subprocess_enabled

    if subprocess_enabled():
        payload = run_pickled_job(
            {
                "op": "run_arrow_table",
                "code": code,
                "cfg": cfg or {},
                "table": table,
                "rule_id": rule_id,
                "site_id": site_id,
                "limit": limit,
            },
            timeout_s=_exec_timeout_s(),
        )
        if not payload.get("ok"):
            err = payload.get("error") or "rule execution failed"
            if payload.get("timed_out"):
                err = "rule execution timed out"
            return {
                "ok": False,
                "error": err,
                "events": sanitize_events([{"type": "error", "text": err}]),
            }
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "invalid playground worker result"}
    return _run_arrow_table_impl(
        code,
        table,
        cfg,
        rule_id=rule_id,
        site_id=site_id,
        limit=limit,
    )


def dataframe_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df
