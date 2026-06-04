"""Cookbook helpers for ``evaluate()`` rules — shared by edge, PyPI consumers, and AWS lambda."""

from __future__ import annotations

import statistics
from typing import Any

ROLLING_AVG_MINUTES_ALLOWED = (1, 5, 15)
DEFAULT_ROLLING_AVG_MINUTES = 5

ONE_HOUR_MS = 60 * 60 * 1000
FILL_RATIO = 0.95

DEFAULT_THRESHOLDS_F: dict[str, float] = {
    "flatline_tolerance": 0.10,
    "max_temp_per_hour": 5.0,
    "max_temp_per_15min": 2.0,
    "max_spread": 4.0,
    "max_spread_15min": 2.5,
    "max_spread_24h": 12.0,
    "bounds_low": 65.0,
    "bounds_high": 80.0,
    "flatline_window": 18.0,
    "rolling_window": 6.0,
    "flatline_tolerance_rh": 1.0,
    "bounds_low_rh": 20.0,
    "bounds_high_rh": 70.0,
}


def temp_unit_symbol(cfg: dict[str, Any] | None) -> str:
    unit = str((cfg or {}).get("temp_unit") or "imperial").lower()
    return "°C" if unit in {"metric", "c", "celsius"} else "°F"


def normalize_rolling_avg_minutes(value: Any) -> int:
    try:
        m = int(value)
    except (TypeError, ValueError):
        m = DEFAULT_ROLLING_AVG_MINUTES
    if m not in ROLLING_AVG_MINUTES_ALLOWED:
        return min(ROLLING_AVG_MINUTES_ALLOWED, key=lambda x: abs(x - m))
    return m


def cfg_threshold(cfg: dict[str, Any] | None, key: str) -> float:
    cfg = cfg or {}
    if key in cfg and cfg[key] is not None and str(cfg[key]).strip() != "":
        return float(cfg[key])
    return float(DEFAULT_THRESHOLDS_F.get(key, 0.0))


def window_rows_1h(row: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now_ms = int(row["ts_ms"])
    start_ms = now_ms - ONE_HOUR_MS
    return [r for r in rows if start_ms <= int(r["ts_ms"]) <= now_ms]


def hour_window_ready(window_rows: list[dict[str, Any]]) -> bool:
    if len(window_rows) < 2:
        return False
    ts_vals = [int(r["ts_ms"]) for r in window_rows if r.get("ts_ms") is not None]
    if len(ts_vals) < 2:
        return False
    return (max(ts_vals) - min(ts_vals)) >= ONE_HOUR_MS * FILL_RATIO


def _median_sample_ms(rows: list[dict[str, Any]]) -> int:
    if len(rows) < 2:
        return 60_000
    dts = [
        int(rows[i]["ts_ms"]) - int(rows[i - 1]["ts_ms"])
        for i in range(1, len(rows))
        if int(rows[i]["ts_ms"]) > int(rows[i - 1]["ts_ms"])
    ]
    return int(statistics.median(dts)) if dts else 60_000


def attach_rolling_avg(rows: list[dict[str, Any]], *, minutes: int = DEFAULT_ROLLING_AVG_MINUTES) -> None:
    """Trailing time-mean on ``temp`` for each row (mutates rows in place)."""
    if not rows:
        return
    minutes = normalize_rolling_avg_minutes(minutes)
    window_ms = minutes * 60_000
    period_ms = _median_sample_ms(rows)
    j_start = 0
    for i, row in enumerate(rows):
        ts = int(row["ts_ms"])
        cutoff = ts - window_ms
        while j_start < i and int(rows[j_start]["ts_ms"]) < cutoff:
            j_start += 1
        window = rows[j_start : i + 1]
        vals = [float(r["temp"]) for r in window if r.get("temp") is not None]
        avg = sum(vals) / len(vals) if vals else row.get("temp")
        row["temp_rolling_avg"] = avg
        row["degF_rolling_avg"] = avg
        row["temp_raw"] = row.get("temp")
        row["sample_period_ms"] = period_ms
        row["rolling_avg_minutes"] = minutes
        row["samples_in_avg"] = len(window)
        row["rolling_window_ms"] = window_ms


def inject_cookbook_helpers(globals_dict: dict[str, Any]) -> None:
    """Inject into a rule sandbox (used by ``rule_globals()``)."""
    globals_dict["temp_unit_symbol"] = temp_unit_symbol
    globals_dict["cfg_threshold"] = cfg_threshold
    globals_dict["window_rows_1h"] = window_rows_1h
    globals_dict["hour_window_ready"] = hour_window_ready
    globals_dict["ONE_HOUR_MS"] = ONE_HOUR_MS
