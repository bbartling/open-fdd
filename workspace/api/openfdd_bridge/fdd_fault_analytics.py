"""Summarize fault episodes from FDD sweep rows for check-engine display."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _parse_ts_ms(row: dict[str, Any]) -> int | None:
    raw = row.get("ts_ms")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    for key in ("timestamp", "ts"):
        val = row.get(key)
        if val is None:
            continue
        try:
            ts = pd.to_datetime(val, utc=True, errors="coerce")
            if pd.isna(ts):
                continue
            return int(ts.value // 1_000_000)
        except (TypeError, ValueError):
            continue
    return None


def _format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    if seconds < 90:
        return f"{int(round(seconds))} sec"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.1f} min"
    hours = minutes / 60.0
    if hours < 48:
        return f"{hours:.1f} h"
    days = hours / 24.0
    return f"{days:.1f} d"


def summarize_fault_run(
    rows: list[dict[str, Any]],
    flags: list[bool],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return analytics for flagged samples (avg value, duration, bounds)."""
    cfg = config or {}
    if not rows or not flags:
        return {}

    fault_rows: list[dict[str, Any]] = []
    for i, flagged in enumerate(flags):
        if flagged and i < len(rows):
            fault_rows.append(rows[i])
    if not fault_rows:
        return {}

    vals: list[float] = []
    ts_list: list[int] = []
    columns: set[str] = set()
    for row in fault_rows:
        col = str(row.get("value_column") or "")
        if col:
            columns.add(col)
        ts = _parse_ts_ms(row)
        if ts is not None:
            ts_list.append(ts)
        v = row.get("temp")
        if v is None:
            v = row.get("rh")
        try:
            if v is not None:
                vals.append(float(v))
        except (TypeError, ValueError):
            pass

    out: dict[str, Any] = {
        "fault_samples": len(fault_rows),
        "total_samples": len(rows),
        "value_columns": sorted(columns),
    }

    if vals:
        out["avg_value_fault"] = round(sum(vals) / len(vals), 2)
        out["min_value_fault"] = round(min(vals), 2)
        out["max_value_fault"] = round(max(vals), 2)
        unit = "°F"
        if fault_rows[0].get("value_kind") == "rh":
            unit = "%RH"
        out["value_unit"] = unit

    low = cfg.get("bounds_low")
    high = cfg.get("bounds_high")
    if low is not None and str(low).strip() != "":
        out["bounds_low"] = float(low)
    if high is not None and str(high).strip() != "":
        out["bounds_high"] = float(high)

    if ts_list:
        ts_list.sort()
        span_sec = max(0, (ts_list[-1] - ts_list[0]) / 1000.0)
        out["fault_span_sec"] = round(span_sec, 1)
        out["fault_span_label"] = _format_duration(span_sec)
        # Estimate contiguous fault duration using median sample period
        if len(ts_list) >= 2:
            gaps = [ts_list[i] - ts_list[i - 1] for i in range(1, len(ts_list))]
            period_ms = int(pd.Series(gaps).median()) if gaps else 60_000
            period_ms = max(period_ms, 1)
            out["sample_period_sec"] = round(period_ms / 1000.0, 1)
            out["estimated_fault_duration_sec"] = round(
                len(fault_rows) * period_ms / 1000.0, 1
            )
            out["estimated_fault_duration_label"] = _format_duration(
                float(out["estimated_fault_duration_sec"])
            )

    sym = str(cfg.get("temp_unit") or "imperial")
    out["temp_unit_setting"] = sym
    return out


def format_fault_detail(analytics: dict[str, Any], *, source: str = "") -> str:
    if not analytics:
        return ""
    parts: list[str] = []
    fs = analytics.get("fault_samples")
    ts = analytics.get("total_samples")
    if fs is not None and ts is not None:
        parts.append(f"{fs}/{ts} samples flagged")
    avg = analytics.get("avg_value_fault")
    if avg is not None:
        unit = analytics.get("value_unit") or ""
        lo = analytics.get("bounds_low")
        hi = analytics.get("bounds_high")
        band = f" (band {lo}–{hi}{unit})" if lo is not None and hi is not None else ""
        parts.append(f"avg {avg}{unit} while fault{band}")
    dur = analytics.get("estimated_fault_duration_label") or analytics.get("fault_span_label")
    if dur:
        parts.append(f"~{dur} in lookback")
    cols = analytics.get("value_columns") or []
    if cols:
        parts.append(f"column: {', '.join(cols[:3])}" + ("…" if len(cols) > 3 else ""))
    if source:
        parts.append(f"({source})")
    return ". ".join(parts) + ("." if parts else "")
