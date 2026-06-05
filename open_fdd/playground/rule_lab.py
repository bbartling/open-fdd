"""
Rule Lab + go-live AFDD: lint, sweep, chart downsample, chunked backfill.

AWS ``web_lambda`` parity — temp-unit aware rolling avg, ``apply_faults`` batch mode,
retroactive window paint, and 6 h × 7 d chunked evaluation.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import csv
import datetime
import io
import math
import re
import statistics
import time
import traceback
from contextlib import redirect_stdout
from typing import Any, Callable

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    NUMPY_AVAILABLE = False

ALLOWED_IMPORT_ROOTS = frozenset({"datetime", "math", "numpy"})
ROLLING_AVG_MINUTES_ALLOWED = (1, 5, 10)
DEFAULT_ROLLING_AVG_MINUTES = 1

# Go live AFDD backfill — fixed (not the Rule Lab test-window dropdown).
GO_LIVE_BATCH_HOURS = 6
GO_LIVE_MAX_LOOKBACK_HOURS = 168  # 7 days
GO_LIVE_OVERLAP_MINUTES = 15


def normalize_rolling_avg_minutes(value: Any) -> int:
    """Clamp to allowed windows: 1, 5, or 10 minutes."""
    try:
        m = int(value)
    except (TypeError, ValueError):
        m = DEFAULT_ROLLING_AVG_MINUTES
    if m not in ROLLING_AVG_MINUTES_ALLOWED:
        return min(ROLLING_AVG_MINUTES_ALLOWED, key=lambda x: abs(x - m))
    return m


def lint_python(code: str) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not code.strip():
        return {"ok": True, "issues": issues}
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        line = e.lineno or 1
        col = e.offset or 1
        issues.append(
            {
                "line": line,
                "col": col,
                "end_col": col + 1,
                "message": e.msg or "invalid syntax",
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
        raise ImportError(f"import of '{name}' not allowed (allowed: {', '.join(sorted(ALLOWED_IMPORT_ROOTS))})")
    return _builtins.__import__(name, globals, locals, fromlist, level)


def _sandbox_builtins() -> dict[str, Any]:
    return {
        "print": print,
        "range": range,
        "len": len,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "sum": sum,
        "enumerate": enumerate,
        "zip": zip,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "True": True,
        "False": False,
        "None": None,
        "__import__": _restricted_import,
    }


def _normalize_hit(raw: Any) -> bool:
    if raw is None or raw is False:
        return False
    if raw is True:
        return True
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return True
    if isinstance(raw, dict):
        return True
    return bool(raw)


def _indices_to_paint(paint_payload: Any, rows: list[dict[str, Any]]) -> list[int]:
    """Resolve row indices from evaluate()'s second return value (window rows)."""
    if not paint_payload:
        return []
    if not isinstance(paint_payload, list):
        return []
    out: list[int] = []
    for item in paint_payload:
        if not isinstance(item, dict):
            continue
        if "row" in item:
            try:
                out.append(int(item["row"]))
            except (TypeError, ValueError):
                pass
            continue
        ts = item.get("ts_ms")
        if ts is not None:
            for i, r in enumerate(rows):
                if int(r["ts_ms"]) == int(ts):
                    out.append(i)
                    break
    return out


def _parse_evaluate_result(
    raw: Any, rows: list[dict[str, Any]]
) -> tuple[bool, list[int]]:
    """
    evaluate() may return:
      - bool (flag current row only)
      - (bool, window_rows) — when True, flag every row in window_rows (retroactive)
    """
    if isinstance(raw, tuple) and len(raw) >= 1:
        hit = _normalize_hit(raw[0])
        if hit and len(raw) >= 2:
            return hit, _indices_to_paint(raw[1], rows)
        return hit, []
    return _normalize_hit(raw), []


def compile_rule_code(code: str) -> tuple[Callable[..., Any], Callable[..., Any] | None]:
    """Load evaluate(); optional apply_faults(rows, cfg) -> list[bool] same length as rows."""
    sandbox = _rule_sandbox()
    exec(compile(code, "<rule>", "exec"), sandbox, sandbox)
    fn = sandbox.get("evaluate")
    if not callable(fn):
        raise ValueError("Rule code must define evaluate(row, cfg, prev_row=None, rows=None)")
    apply_fn = sandbox.get("apply_faults")
    if apply_fn is not None and not callable(apply_fn):
        raise ValueError("apply_faults must be a function(rows, cfg)")
    return fn, apply_fn if callable(apply_fn) else None


def compile_evaluate(code: str) -> Callable[..., Any]:
    evaluate, _ = compile_rule_code(code)
    return evaluate


def readings_to_rows(readings: list[dict]) -> list[dict[str, Any]]:
    """Build row dicts for evaluate()."""
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(readings):
        ts_iso = r.get("ts_iso") or ""
        rows.append(
            {
                "row": i,
                "ts_ms": int(r["ts_ms"]),
                "ts": ts_iso.replace("T", " ")[:19],
                "degF": float(r["degF"]),
                "degC": float(r.get("degC", 0)),
                "seq": r.get("seq"),
                "source": r.get("source"),
            }
        )
    return rows


def _median_sample_ms(rows: list[dict[str, Any]]) -> int:
    if len(rows) < 2:
        return 10_000
    dts = [
        int(rows[i]["ts_ms"]) - int(rows[i - 1]["ts_ms"])
        for i in range(1, len(rows))
        if int(rows[i]["ts_ms"]) > int(rows[i - 1]["ts_ms"])
    ]
    if not dts:
        return 10_000
    return int(statistics.median(dts))


def attach_rolling_avg(
    rows: list[dict[str, Any]],
    window_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
    temp_unit: str = "imperial",
) -> None:
    """
    Mutates rows in place. Trailing mean over samples with
    ts_ms in [row.ts_ms - window_minutes*60_000, row.ts_ms].
    Always sets degF_* (MQTT); also temp/temp_rolling_avg in rule unit.
    """
    from open_fdd.playground.temp_units import normalize_temp_unit, temp_from_row

    if not rows:
        return
    minutes = normalize_rolling_avg_minutes(window_minutes)
    unit = normalize_temp_unit(temp_unit)
    window_ms = minutes * 60_000
    period_ms = _median_sample_ms(rows)
    j_start = 0
    for i, row in enumerate(rows):
        row["degF_raw"] = float(row["degF"])
        row["temp_unit"] = unit
        row["temp_raw"] = temp_from_row(row, unit)
        ts = int(row["ts_ms"])
        cutoff = ts - window_ms
        while j_start < i and int(rows[j_start]["ts_ms"]) < cutoff:
            j_start += 1
        window = rows[j_start : i + 1]
        row["degF_rolling_avg"] = sum(r["degF_raw"] for r in window) / len(window)
        row["temp_rolling_avg"] = sum(
            temp_from_row(r, unit) for r in window
        ) / len(window)
        row["temp"] = row["temp_raw"]
        row["sample_period_ms"] = period_ms
        row["rolling_avg_minutes"] = minutes
        row["rolling_window_ms"] = window_ms
        row["samples_in_avg"] = len(window)


def prepare_rows_for_evaluate(
    rows: list[dict[str, Any]],
    rolling_avg_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
    temp_unit: str = "imperial",
) -> list[dict[str, Any]]:
    """Enrich rows before a sweep; recomputes when window or unit changes."""
    from open_fdd.playground.temp_units import normalize_temp_unit

    if not rows:
        return rows
    minutes = normalize_rolling_avg_minutes(rolling_avg_minutes)
    unit = normalize_temp_unit(temp_unit)
    need = (
        rows[0].get("rolling_avg_minutes") != minutes
        or rows[0].get("temp_unit") != unit
        or "degF_rolling_avg" not in rows[0]
        or "temp_rolling_avg" not in rows[0]
    )
    if need:
        attach_rolling_avg(rows, minutes, temp_unit=unit)
    return rows


def slim_fdd_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """
    DynamoDB item max ~400 KB. Drop full ts_ms / flag_series (7 d backfill).
    Dashboard recomputes fault_plots on each /api/readings request.
    """
    return {
        k: v
        for k, v in summary.items()
        if k not in ("ts_ms", "flag_series", "aux_series")
    }


def chart_sample_indices(n: int, max_pts: int) -> list[int]:
    """Evenly spaced indices for chart API payloads (keeps first + last)."""
    if n <= 0:
        return []
    if n <= max_pts:
        return list(range(n))
    stride = max(1, (n + max_pts - 2) // (max_pts - 1))
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx[:max_pts]


def downsample_aligned_series(
    n: int,
    max_pts: int,
    readings: list[dict],
    fault_plots: dict[str, list[int]],
    aux_series: dict[str, list[float]],
) -> tuple[list[dict], dict[str, list[int]], dict[str, list[float]], int, bool]:
    """Returns (readings, fault_plots, aux_series, stride, truncated)."""
    if n <= max_pts:
        return readings, fault_plots, aux_series, 1, False
    idx = chart_sample_indices(n, max_pts)
    stride = max(1, n // max(len(idx) - 1, 1))
    out_readings = [readings[i] for i in idx]
    out_plots = {k: [series[i] for i in idx] for k, series in fault_plots.items()}
    out_aux: dict[str, list[float]] = {}
    for k, series in aux_series.items():
        if len(series) == n:
            out_aux[k] = [series[i] for i in idx]
    return out_readings, out_plots, out_aux, stride, True


def csv_fault_column(rule_id: str) -> str:
    slug = re.sub(r"[^\w]+", "_", str(rule_id or "rule")).strip("_") or "rule"
    return f"fault_{slug}"


def build_readings_csv(
    readings: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    fault_plots: dict[str, list[int]],
    rules: list[dict[str, Any]],
    fault_rule_ids: list[str] | None = None,
) -> str:
    """Excel-friendly CSV: timestamps, temps, rolling avg, optional fault columns (0/1)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")

    rule_list = [r for r in rules if r.get("enabled", True)]
    if fault_rule_ids is not None:
        allowed = set(fault_rule_ids)
        rule_list = [r for r in rule_list if r.get("id") in allowed]

    headers = [
        "time_utc",
        "ts_ms",
        "degF",
        "degC",
        "rolling_avg_degF",
        "rolling_avg_degC",
    ]
    headers.extend(csv_fault_column(r.get("id", "")) for r in rule_list)
    writer.writerow(headers)

    for i, rd in enumerate(readings):
        ts_iso = rd.get("ts_iso") or ""
        if not ts_iso and rd.get("ts_ms") is not None:
            ts_iso = datetime.datetime.fromtimestamp(
                int(rd["ts_ms"]) / 1000, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
        line = [
            ts_iso,
            rd.get("ts_ms", ""),
            f'{float(rd["degF"]):.3f}' if rd.get("degF") is not None else "",
            f'{float(rd["degC"]):.3f}' if rd.get("degC") is not None else "",
        ]
        if rows and i < len(rows) and rows[i].get("degF_rolling_avg") is not None:
            avg_f = float(rows[i]["degF_rolling_avg"])
            line.append(f"{avg_f:.3f}")
            line.append(f"{((avg_f - 32) * 5 / 9):.3f}")
        else:
            line.extend(["", ""])
        for rule in rule_list:
            flags = fault_plots.get(rule.get("id", ""), [])
            line.append("1" if i < len(flags) and flags[i] else "0")
        writer.writerow(line)

    return buf.getvalue()


def eval_rows_preview(rows: list[dict[str, Any]], limit: int = 200) -> list[dict[str, Any]]:
    """Slim row dicts for Rule Lab table (last N samples)."""
    slim_keys = (
        "row",
        "ts",
        "degF",
        "degF_raw",
        "degF_rolling_avg",
        "sample_period_ms",
        "rolling_avg_minutes",
        "samples_in_avg",
    )
    out: list[dict[str, Any]] = []
    for r in rows[-limit:]:
        out.append({k: r[k] for k in slim_keys if k in r})
    return out


def aux_series_from_rows(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Chart overlay from enriched rows or rule-authored degF_1min_avg."""
    if not rows:
        return {}
    if "degF_1min_avg" in rows[0]:
        return {
            "degF_1min_avg": [float(r["degF_1min_avg"]) for r in rows],
            "degF_raw": [float(r.get("degF_raw", r["degF"])) for r in rows],
        }
    if "degF_rolling_avg" in rows[0]:
        return {
            "degF_1min_avg": [float(r["degF_rolling_avg"]) for r in rows],
            "degF_raw": [float(r.get("degF_raw", r["degF"])) for r in rows],
        }
    return {}


def _rule_sandbox() -> dict[str, Any]:
    from open_fdd.playground.temp_units import (
        effective_temp_unit,
        resolve_cfg_threshold,
        temp_from_row,
        temp_unit_symbol,
    )

    def cfg_threshold(cfg: dict[str, Any], base_key: str) -> float:
        return resolve_cfg_threshold(cfg or {}, base_key, effective_temp_unit(cfg))

    sandbox: dict[str, Any] = {
        "__builtins__": _sandbox_builtins(),
        "__name__": "__rule__",
        "math": math,
        "datetime": datetime,
        "timezone": datetime.timezone,
        "effective_temp_unit": effective_temp_unit,
        "temp_from_row": temp_from_row,
        "temp_unit_symbol": temp_unit_symbol,
        "cfg_threshold": cfg_threshold,
        "resolve_cfg_threshold": cfg_threshold,
    }
    if NUMPY_AVAILABLE and np is not None:
        sandbox["np"] = np
        sandbox["numpy"] = np
    return sandbox


def compile_evaluate(code: str) -> Callable[..., Any]:
    sandbox = _rule_sandbox()
    exec(compile(code, "<rule>", "exec"), sandbox, sandbox)
    fn = sandbox.get("evaluate")
    if not callable(fn):
        raise ValueError("Rule code must define evaluate(row, cfg, prev_row=None, rows=None)")
    return fn


def sweep_rule(
    code: str,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    capture_print: bool = True,
    rolling_avg_minutes: int | None = None,
    series_ctx: dict[str, Any] | None = None,
) -> tuple[list[int], list[dict[str, Any]]]:
    """
    Returns (flag_series 0/1 per raw row, events for console UI).

    Per-row mode: evaluate() -> bool flags that row only.
    Retroactive mode: evaluate() -> (True, window_rows) flags every row in the window.
    Batch mode: optional apply_faults(rows, cfg) -> list[bool] (same length as rows).
    """
    events: list[dict[str, Any]] = []
    lint = lint_python(code)
    if not lint["ok"]:
        return [], [{"type": "error", "text": "syntax error — fix before run\n"}]

    minutes = normalize_rolling_avg_minutes(
        rolling_avg_minutes
        if rolling_avg_minutes is not None
        else cfg.get("rolling_avg_minutes", DEFAULT_ROLLING_AVG_MINUTES)
    )
    from open_fdd.playground.temp_units import effective_temp_unit, temp_unit_symbol

    temp_unit = effective_temp_unit(cfg)
    prepare_rows_for_evaluate(rows, minutes, temp_unit=temp_unit)
    evaluate, apply_faults = compile_rule_code(code)
    unit_sym = temp_unit_symbol(temp_unit)
    stream_buf: list[dict[str, Any]] = []

    class _Cap(io.TextIOBase):
        def write(self, s: str) -> int:
            if s and capture_print:
                stream_buf.append({"type": "stdout", "text": s})
            return len(s or "")

    cap = _Cap()
    mode = "apply_faults" if apply_faults else "per_row"
    events.append(
        {
            "type": "stdout",
            "text": (
                f"--- sweeping {len(rows)} rows "
                f"(temp in {unit_sym}, rolling avg {minutes} min by ts_ms, mode={mode}) ---\n"
            ),
        }
    )

    flags = [0] * len(rows)
    tripped = 0
    painted: set[int] = set()
    row_errors: list[str] = []

    if apply_faults:
        stream_buf.clear()
        try:
            with redirect_stdout(cap):
                raw_flags = apply_faults(rows, cfg)
            for ev in stream_buf:
                events.append(ev)
            if not isinstance(raw_flags, list):
                raise ValueError("apply_faults must return a list[bool] same length as rows")
            if len(raw_flags) != len(rows):
                raise ValueError(
                    f"apply_faults returned {len(raw_flags)} flags, expected {len(rows)}"
                )
            for i, v in enumerate(raw_flags):
                flags[i] = 1 if v else 0
            tripped = sum(flags)
            for i, row in enumerate(rows):
                events.append(
                    {
                        "type": "row",
                        "row": row["row"],
                        "ts": row["ts"],
                        "status": "fault" if flags[i] else "ok",
                        "degF": row["degF"],
                        "raw_hit": bool(flags[i]),
                    }
                )
        except Exception as exc:
            events.append({"type": "stdout", "text": f"apply_faults ERROR: {exc}\n"})
            if not capture_print:
                raise RuntimeError(f"apply_faults failed: {exc}") from exc
            return [], events
    else:
        for i, row in enumerate(rows):
            prev = rows[i - 1] if i else None
            stream_buf.clear()
            instant = False
            try:
                with redirect_stdout(cap):
                    if series_ctx is not None:
                        try:
                            result = evaluate(row, cfg, prev, rows, series=series_ctx)
                        except TypeError:
                            result = evaluate(row, cfg, prev, rows)
                    else:
                        result = evaluate(row, cfg, prev, rows)
                    instant, paint_idxs = _parse_evaluate_result(result, rows)
                for ev in stream_buf:
                    events.append(ev)
                if paint_idxs:
                    for j in paint_idxs:
                        if 0 <= j < len(flags):
                            flags[j] = 1
                            painted.add(j)
                elif instant:
                    flags[i] = 1
                    painted.add(i)
                    tripped += 1
                status = "fault" if i in painted else "ok"
                events.append(
                    {
                        "type": "row",
                        "row": row["row"],
                        "ts": row["ts"],
                        "status": status,
                        "degF": row["degF"],
                        "raw_hit": instant,
                        "painted": i in painted and not instant,
                    }
                )
            except Exception as exc:
                row_errors.append(f"row {row['row']}: {exc}")
                events.append(
                    {
                        "type": "row",
                        "row": row["row"],
                        "ts": row["ts"],
                        "status": "error",
                        "message": str(exc),
                    }
                )
                events.append(
                    {"type": "stdout", "text": f"  row {row['row']}: ERROR {exc}\n"}
                )

    if row_errors and not capture_print:
        extra = f" (+{len(row_errors) - 1} more)" if len(row_errors) > 1 else ""
        raise RuntimeError(f"rule sweep failed: {row_errors[0]}{extra}")

    events.append(
        {
            "type": "summary",
            "rows": len(rows),
            "raw_tripped": tripped,
            "flagged": sum(flags),
            "sweep_mode": mode,
        }
    )
    events.append(
        {
            "type": "stdout",
            "text": (
                f"--- done: {sum(flags)} flagged ({mode}), {len(rows)} rows ---\n"
            ),
        }
    )
    return flags, events


ONE_HOUR_MS = 60 * 60 * 1000
WINDOW_TRACE_FILL_RATIO = 0.95


def window_trace_events(
    rows: list[dict[str, Any]],
    *,
    window_ms: int = ONE_HOUR_MS,
    fill_ratio: float = WINDOW_TRACE_FILL_RATIO,
    temp_unit: str = "imperial",
    sample_every: int = 60,
    max_lines: int = 40,
) -> list[dict[str, Any]]:
    """
    Diagnostic stdout for Rule Lab verbose test.
    Shows rolling window spread samples (rule print() still only runs on fault).
    """
    from open_fdd.playground.temp_units import temp_unit_symbol

    if not rows:
        return []

    sym = temp_unit_symbol(temp_unit)
    out: list[dict[str, Any]] = []
    lines = 0
    spreads: list[float] = []
    full_windows = 0
    window_min = window_ms // 60_000

    for i, row in enumerate(rows):
        start_ms = row["ts_ms"] - window_ms
        win = [r for r in rows if start_ms <= r["ts_ms"] <= row["ts_ms"]]
        if len(win) < 2:
            continue
        span = win[-1]["ts_ms"] - win[0]["ts_ms"]
        if span < window_ms * fill_ratio:
            continue
        full_windows += 1
        vals = [r["temp"] for r in win]
        spread = max(vals) - min(vals)
        spreads.append(spread)
        if lines >= max_lines:
            continue
        if i % sample_every != 0 and i != len(rows) - 1:
            continue
        lines += 1
        out.append(
            {
                "type": "stdout",
                "text": (
                    f"[trace] row={row['row']} ts={row['ts']} "
                    f"window_spread={spread:.3f} {sym} samples={len(win)}\n"
                ),
            }
        )

    if spreads:
        header = (
            f"[trace] {full_windows} rows with full {window_min} min window; "
            f"spread min={min(spreads):.3f} max={max(spreads):.3f} {sym}. "
            f"Rule print() runs only on fault — use trace lines to tune tolerance.\n"
        )
    else:
        header = (
            f"[trace] no full {window_min} min window in this test slice — "
            f"use Test window ≥ 2 h for 1 h lookback rules.\n"
        )
    return [{"type": "stdout", "text": header}] + out


def fault_analytics_from_series(
    flag_series: dict[str, list[int]],
    rows: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-rule fault hit count and estimated elapsed time in the history window."""
    period_ms = _median_sample_ms(rows) if rows else 10_000
    meta_by_id = {r["id"]: r for r in rules}
    analytics: list[dict[str, Any]] = []

    for rule_id, flags in flag_series.items():
        if not flags:
            continue
        count = int(sum(1 for f in flags if f))
        elapsed_ms = 0
        for i, flagged in enumerate(flags):
            if not flagged:
                continue
            if i + 1 < len(rows):
                elapsed_ms += max(
                    0, int(rows[i + 1]["ts_ms"]) - int(rows[i]["ts_ms"])
                )
            else:
                elapsed_ms += period_ms

        rule = meta_by_id.get(rule_id, {})
        analytics.append(
            {
                "id": rule_id,
                "title": rule.get("title", rule_id),
                "color": rule.get("color", "#8b949e"),
                "enabled": rule.get("enabled", True) is not False,
                "count": count,
                "elapsed_ms": elapsed_ms,
            }
        )

    analytics.sort(key=lambda x: x["count"], reverse=True)
    return analytics


def build_series_context(
    series_map: dict[str, list[dict[str, Any]]],
    row_index: int,
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build per-row `series` dict for cross-sensor rules.
    aliases maps rule keys (SAT) → series_id.
    Each entry: {"values": [...], "current": float|None, "series_id": str}
    """
    ctx: dict[str, Any] = {}
    alias_to_sid = aliases or {}
    sid_to_alias = {v: k for k, v in alias_to_sid.items()}

    for sid, samples in series_map.items():
        values = [s.get("value") for s in samples]
        cur = values[row_index] if 0 <= row_index < len(values) else None
        entry = {"values": values, "current": cur, "series_id": sid}
        ctx[sid] = entry
        alias = sid_to_alias.get(sid)
        if alias:
            ctx[alias] = entry
    return ctx


def evaluate_rules_on_series(
    rules: list[dict[str, Any]],
    primary_rows: list[dict[str, Any]],
    series_map: dict[str, list[dict[str, Any]]],
    *,
    default_rolling_avg_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
) -> dict[str, list[int]]:
    """Evaluate rules with cross-sensor series context aligned to primary_rows length."""
    n = len(primary_rows)
    if n == 0:
        return {}
    out: dict[str, list[int]] = {}
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        code = rule.get("code") or ""
        cfg = rule.get("config") or {}
        aliases = cfg.get("series_aliases") or {}
        flags = [0] * n
        for i in range(n):
            series_ctx = build_series_context(series_map, i, aliases=aliases)
            row = primary_rows[i]
            prev = primary_rows[i - 1] if i else None
            chunk_flags, _events = sweep_rule(
                code,
                cfg,
                [row],
                capture_print=False,
                rolling_avg_minutes=cfg.get("rolling_avg_minutes", default_rolling_avg_minutes),
                series_ctx=series_ctx,
            )
            if chunk_flags and chunk_flags[0]:
                flags[i] = 1
        out[rule["id"]] = flags
    return out


def evaluate_rules_on_readings(
    rules: list[dict[str, Any]],
    readings: list[dict],
    *,
    rows: list[dict[str, Any]] | None = None,
    default_rolling_avg_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
) -> tuple[dict[str, list[int]], list[dict[str, Any]]]:
    """All enabled rules → flag_series keyed by rule id. Returns (flags, rows) for chart aux."""
    if rows is None:
        rows = readings_to_rows(readings)
    out: dict[str, list[int]] = {}
    chart_minutes = normalize_rolling_avg_minutes(default_rolling_avg_minutes)
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        code = rule.get("code") or ""
        cfg = rule.get("config") or {}
        minutes = normalize_rolling_avg_minutes(
            cfg.get("rolling_avg_minutes", chart_minutes)
        )
        from open_fdd.playground.temp_units import effective_temp_unit

        tunit = effective_temp_unit(cfg)
        prepare_rows_for_evaluate(rows, minutes, temp_unit=tunit)
        flags, _events = sweep_rule(
            code, cfg, rows, capture_print=False, rolling_avg_minutes=minutes
        )
        out[rule["id"]] = flags
        chart_minutes = minutes
    if rows and "degF_rolling_avg" not in rows[0]:
        from open_fdd.playground.temp_units import normalize_temp_unit

        prepare_rows_for_evaluate(
            rows, chart_minutes, temp_unit=normalize_temp_unit(None)
        )
    return out, rows


def evaluate_rules_on_readings_chunked(
    rules: list[dict[str, Any]],
    readings: list[dict],
    *,
    chunk_hours: float = GO_LIVE_BATCH_HOURS,
    overlap_minutes: int = GO_LIVE_OVERLAP_MINUTES,
    default_rolling_avg_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
    display_temp_unit: str = "imperial",
) -> tuple[dict[str, list[int]], list[dict[str, Any]]]:
    """
    Chart / long-window rule eval: 6 h time chunks + overlap (same idea as go-live AFDD).
    Merges per-sample flags with OR across chunks so retroactive rules paint correctly.
    """
    from open_fdd.playground.temp_units import normalize_temp_unit

    n = len(readings)
    if n == 0:
        return {}, []

    enabled = [r for r in rules if r.get("enabled", True)]
    master: dict[str, list[int]] = {r["id"]: [0] * n for r in enabled}

    window_start_ms = int(readings[0]["ts_ms"])
    window_end_ms = int(readings[-1]["ts_ms"]) + 1
    chunk_ms = max(1, int(float(chunk_hours) * 3600 * 1000))
    overlap_ms = max(int(overlap_minutes * 60_000), 10 * 60_000)
    cursor = window_start_ms
    i_scan = 0

    while cursor < window_end_ms:
        chunk_end = min(cursor + chunk_ms, window_end_ms)
        fetch_start = (
            max(window_start_ms, cursor - overlap_ms)
            if cursor > window_start_ms
            else window_start_ms
        )

        while i_scan < n and int(readings[i_scan]["ts_ms"]) < fetch_start:
            i_scan += 1
        i_start = i_scan
        i_end = i_start
        while i_end < n and int(readings[i_end]["ts_ms"]) < chunk_end:
            i_end += 1

        chunk_readings = readings[i_start:i_end]
        if chunk_readings:
            flag_series, _chunk_rows = evaluate_rules_on_readings(
                rules,
                chunk_readings,
                default_rolling_avg_minutes=default_rolling_avg_minutes,
            )
            for rule_id, flags in flag_series.items():
                dest = master.get(rule_id)
                if dest is None:
                    continue
                for j, hit in enumerate(flags):
                    if hit and i_start + j < n:
                        dest[i_start + j] = 1

        cursor = chunk_end

    rows = readings_to_rows(readings)
    prepare_rows_for_evaluate(
        rows,
        normalize_rolling_avg_minutes(default_rolling_avg_minutes),
        temp_unit=normalize_temp_unit(display_temp_unit),
    )
    return master, rows


def count_flags_in_ts_range(
    flag_series: dict[str, list[int]],
    rows: list[dict[str, Any]],
    ts_min_ms: int,
    ts_max_ms: int,
) -> dict[str, int]:
    """Count rule hits only for rows with ts_min_ms <= ts_ms < ts_max_ms."""
    out: dict[str, int] = {}
    for rule_id, flags in flag_series.items():
        n = 0
        for i, hit in enumerate(flags):
            if i >= len(rows):
                break
            ts = int(rows[i]["ts_ms"])
            if ts_min_ms <= ts < ts_max_ms and hit:
                n += 1
        out[rule_id] = n
    return out


def _primary_fdd_status(active_flags: list[str]) -> str:
    if not active_flags:
        return "NORMAL"
    return active_flags[0].replace("_flag", "").upper()


def chunked_evaluate_custom_rules(
    *,
    rules: list[dict[str, Any]],
    lookback_hours: float,
    fetch_interval: Callable[[int, int], list[dict]],
    chunk_hours: float = 6.0,
    default_rolling_avg_minutes: int = DEFAULT_ROLLING_AVG_MINUTES,
    overlap_minutes: int = 15,
    initial_flag_counts: dict[str, int] | None = None,
    window_start_ms: int | None = None,
) -> dict[str, Any]:
    """
    AFDD backfill in time chunks — bounded memory (one chunk of readings at a time).

    fetch_interval(start_ms, end_ms_exclusive) returns readings sorted ascending.
    Overlap rows before each chunk support rolling avg / flatline without double-counting flags.
    """
    now_ms = int(time.time() * 1000)
    if window_start_ms is None:
        window_start_ms = now_ms - int(lookback_hours * 3600 * 1000)
    chunk_ms = max(1, int(chunk_hours * 3600 * 1000))
    overlap_ms = max(int(overlap_minutes * 60_000), 10 * 60_000)

    flag_counts: dict[str, int] = dict(initial_flag_counts or {})
    chunk_log: list[dict[str, Any]] = []
    total_samples = 0
    latest: dict[str, Any] | None = None
    cursor = window_start_ms

    enabled_rules = [r for r in rules if r.get("enabled", True)]
    flag_labels = {r["id"]: r.get("title", r["id"]) for r in enabled_rules}

    eval_log = [
        f"AFDD chunked eval: {lookback_hours}h window · {chunk_hours}h chunks · overlap {overlap_minutes}m",
        f"{len(enabled_rules)} enabled rule(s)",
    ]

    chunk_index = 0
    errors: list[str] = []

    while cursor < now_ms:
        chunk_index += 1
        chunk_end = min(cursor + chunk_ms, now_ms)
        fetch_start = max(window_start_ms, cursor - overlap_ms) if cursor > window_start_ms else cursor
        t0 = time.perf_counter()
        try:
            readings = fetch_interval(fetch_start, chunk_end)
        except Exception as exc:
            err = f"chunk {chunk_index} fetch failed: {exc}"
            errors.append(err)
            eval_log.append(f"  {err}")
            chunk_log.append(
                {
                    "chunk": chunk_index,
                    "start_ms": cursor,
                    "end_ms": chunk_end,
                    "samples": 0,
                    "error": str(exc),
                    "ms": int((time.perf_counter() - t0) * 1000),
                }
            )
            cursor = chunk_end
            continue

        if not readings:
            chunk_log.append(
                {
                    "chunk": chunk_index,
                    "start_ms": cursor,
                    "end_ms": chunk_end,
                    "samples": 0,
                    "flagged_in_chunk": 0,
                    "ms": int((time.perf_counter() - t0) * 1000),
                }
            )
            eval_log.append(f"  chunk {chunk_index}: 0 samples (empty window)")
            cursor = chunk_end
            continue

        try:
            rows = readings_to_rows(readings)
            minutes = normalize_rolling_avg_minutes(default_rolling_avg_minutes)
            prepare_rows_for_evaluate(rows, minutes)
            flag_series, rows = evaluate_rules_on_readings(
                rules, readings, rows=rows, default_rolling_avg_minutes=minutes
            )
        except Exception as exc:
            err = f"chunk {chunk_index} eval failed: {exc}"
            errors.append(err)
            eval_log.append(f"  {err}")
            chunk_log.append(
                {
                    "chunk": chunk_index,
                    "start_ms": cursor,
                    "end_ms": chunk_end,
                    "fetched": len(readings),
                    "samples": 0,
                    "error": str(exc),
                    "ms": int((time.perf_counter() - t0) * 1000),
                }
            )
            cursor = chunk_end
            continue

        chunk_counts = count_flags_in_ts_range(flag_series, rows, cursor, chunk_end)
        chunk_flagged = sum(chunk_counts.values())
        for rid, n in chunk_counts.items():
            flag_counts[rid] = flag_counts.get(rid, 0) + n

        in_chunk = sum(1 for r in rows if cursor <= int(r["ts_ms"]) < chunk_end)
        total_samples += in_chunk
        for r in reversed(rows):
            if cursor <= int(r["ts_ms"]) < chunk_end:
                latest = {
                    "ts_ms": r["ts_ms"],
                    "degF": r["degF"],
                    "degC": r.get("degC"),
                }
                break

        ms = int((time.perf_counter() - t0) * 1000)
        chunk_log.append(
            {
                "chunk": chunk_index,
                "start_ms": cursor,
                "end_ms": chunk_end,
                "samples": in_chunk,
                "fetched": len(readings),
                "flagged_in_chunk": chunk_flagged,
                "ms": ms,
            }
        )
        eval_log.append(
            f"  chunk {chunk_index}: {in_chunk} samples, {chunk_flagged} flags, {ms} ms"
        )
        cursor = chunk_end

    if errors:
        eval_log.append(f"  chunk errors: {len(errors)} (see chunk_log.error)")

    active_flags: list[str] = []
    for key, count in flag_counts.items():
        if count > 0:
            active_flags.append(key)

    summary: dict[str, Any] = {
        "fdd_status": _primary_fdd_status(active_flags),
        "active_flags": active_flags,
        "flag_counts": flag_counts,
        "sample_count": total_samples,
        "lookback_hours": lookback_hours,
        "custom_rules": True,
        "flag_labels": flag_labels,
        "afdd_format": "chunked_v1",
        "chunk_hours": chunk_hours,
        "chunk_count": len(chunk_log),
        "chunk_errors": errors,
        "chunk_log": chunk_log[-40:],
        "eval_log": eval_log
        + [
            f"  total flagged (sum of chunks): {sum(flag_counts.values())}",
            "  chart lanes: live /api/readings (downsampled)",
        ],
        "evaluated_at": int(time.time()),
        "watermark_ms": now_ms,
    }
    if latest:
        summary["latest_degF"] = latest["degF"]
        summary["latest_degC"] = latest.get("degC")
    return summary
