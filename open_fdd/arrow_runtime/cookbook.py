"""Arrow-native FDD cookbook — flatline, spread, OOB, schedule faults (PyArrow only)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.playground.cookbook import cfg_threshold

from .windows import arrow_consecutive_true, arrow_rolling_max, arrow_rolling_min

_SKIP_META = frozenset({"timestamp", "ts", "site_id", "equipment_id", "ts_ms"})


def value_column(table: pa.Table, cfg: dict[str, Any], explicit: str | None = None) -> str:
    if explicit and explicit in table.column_names:
        return explicit
    for key in ("value_column", "column"):
        raw = str(cfg.get(key) or "").strip()
        if raw and raw in table.column_names:
            return raw
    for name in table.column_names:
        if name not in _SKIP_META:
            return name
    raise KeyError("no historian value column in table")


def _window_samples(cfg: dict[str, Any]) -> int:
    return max(2, int(cfg.get("flatline_window_samples") or cfg.get("window_samples") or 12))


def arrow_rolling_mean(array: pa.Array | pa.ChunkedArray, window: int) -> pa.ChunkedArray:
    flat = pc.cast(array, pa.float64())
    n = len(flat)
    if window <= 1 or n == 0:
        return flat
    out: list[float | None] = []
    for i in range(n):
        start = max(0, i - window + 1)
        chunk = flat.slice(start, i - start + 1)
        valid = pc.drop_null(chunk)
        if len(valid) == 0:
            out.append(None)
        else:
            out.append(pc.mean(valid).as_py())
    return pa.array(out, type=pa.float64())


def flatline_1h_mask(table: pa.Table, cfg: dict[str, Any], *, col: str | None = None) -> pa.ChunkedArray:
    """True when rolling min-max spread is below tolerance (~1 h at default poll rate)."""
    name = value_column(table, cfg, col)
    vals = pc.cast(table[name], pa.float64())
    window = _window_samples(cfg)
    tol_key = "flatline_tolerance_rh" if cfg.get("value_kind") == "rh" else "flatline_tolerance"
    tol = cfg_threshold(cfg, tol_key)
    rmin = arrow_rolling_min(vals, window)
    rmax = arrow_rolling_max(vals, window)
    spread = pc.subtract(rmax, rmin)
    return pc.less_equal(pc.abs(spread), tol)


def spread_1h_mask(table: pa.Table, cfg: dict[str, Any], *, col: str | None = None) -> pa.ChunkedArray:
    """True when rolling spread exceeds max_spread."""
    name = value_column(table, cfg, col)
    vals = pc.cast(table[name], pa.float64())
    window = _window_samples(cfg)
    lim = cfg_threshold(cfg, "max_spread")
    rmin = arrow_rolling_min(vals, window)
    rmax = arrow_rolling_max(vals, window)
    spread = pc.subtract(rmax, rmin)
    return pc.greater(spread, lim)


def oob_mask(table: pa.Table, cfg: dict[str, Any], *, col: str | None = None) -> pa.ChunkedArray:
    """True when value (rolling mean when configured) is outside bounds."""
    name = value_column(table, cfg, col)
    vals = pc.cast(table[name], pa.float64())
    minutes = int(cfg.get("rolling_avg_minutes") or 1)
    window = max(1, minutes)
    series = arrow_rolling_mean(vals, window) if minutes > 0 else vals
    is_rh = cfg.get("value_kind") == "rh"
    low_key = "bounds_low_rh" if is_rh else "bounds_low"
    high_key = "bounds_high_rh" if is_rh else "bounds_high"
    low = cfg_threshold(cfg, low_key)
    high = cfg_threshold(cfg, high_key)
    too_low = pc.less(series, low)
    too_high = pc.greater(series, high)
    return pc.or_(too_low, too_high)


def _cfg_list(cfg: dict[str, Any], key: str, default: list[str]) -> list[str]:
    raw = cfg.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(default)


def _column_float(table: pa.Table, col: str) -> pa.ChunkedArray | None:
    if col not in table.column_names:
        return None
    return pc.cast(table[col], pa.float64())


def _fan_on_mask(table: pa.Table, cfg: dict[str, Any]) -> pa.ChunkedArray:
    speed_col = str(cfg.get("fan_speed_col") or "supply-fan-speed-command")
    binary_col = str(cfg.get("fan_binary_col") or "supply-fan-start-stop-command")
    threshold = float(cfg.get("fan_on_threshold") or 5.0)
    mask = pa.array([False] * table.num_rows, type=pa.bool_())
    speed = _column_float(table, speed_col)
    if speed is not None:
        mask = pc.or_(mask, pc.greater(speed, threshold))
    if binary_col in table.column_names:
        raw = table[binary_col]
        num = pc.cast(raw, pa.float64())
        mask = pc.or_(mask, pc.greater(num, 0.5))
    return mask


def _rowwise_mean(columns: list[pa.ChunkedArray]) -> pa.ChunkedArray:
    if not columns:
        return pa.array([], type=pa.float64())
    n = len(columns[0])
    out: list[float | None] = []
    for i in range(n):
        vals = [float(c[i].as_py()) for c in columns if c[i].as_py() is not None]
        out.append(sum(vals) / len(vals) if vals else None)
    return pa.array(out, type=pa.float64())


def _zone_avg(table: pa.Table, cfg: dict[str, Any]) -> pa.ChunkedArray:
    cols = _cfg_list(
        cfg,
        "zone_avg_cols",
        [
            "averagespacetemperature-first-floor-area-2",
            "averagespacetemperature-second-floor-area-3",
        ],
    )
    parts: list[pa.ChunkedArray] = []
    for col in cols:
        arr = _column_float(table, col)
        if arr is not None:
            parts.append(arr)
    if parts:
        return _rowwise_mean(parts)
    for fallback in ("Zone_Air_Temperature_Sensor", "avg_zone_temp"):
        arr = _column_float(table, fallback)
        if arr is not None:
            return arr
    return pa.array([None] * table.num_rows, type=pa.float64())


def _unoccupied_mask(table: pa.Table, cfg: dict[str, Any]) -> pa.ChunkedArray:
    from datetime import datetime, timedelta, timezone

    ts_col = "timestamp" if "timestamp" in table.column_names else "ts"
    tz_hours = float(cfg.get("tz_offset_hours") if cfg.get("tz_offset_hours") is not None else -6)
    start = int(cfg.get("occupied_start_hour") or 8)
    end = int(cfg.get("occupied_end_hour") or 17)
    local_tz = timezone(timedelta(hours=tz_hours))
    out: list[bool] = []
    for val in table[ts_col].to_pylist():
        if val is None:
            out.append(False)
            continue
        if isinstance(val, datetime):
            utc = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        else:
            utc = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            if utc.tzinfo is None:
                utc = utc.replace(tzinfo=timezone.utc)
        local = utc.astimezone(local_tz)
        if local.weekday() >= 5:
            out.append(True)
            continue
        out.append(local.hour < start or local.hour >= end)
    return pa.array(out, type=pa.bool_())


def after_hours_fan_satisfied_mask(table: pa.Table, cfg: dict[str, Any]) -> pa.ChunkedArray:
    """Fan on during unoccupied hours while zone average is in comfort band."""
    fan_on = _fan_on_mask(table, cfg)
    unoccupied = _unoccupied_mask(table, cfg)
    avg = _zone_avg(table, cfg)
    low = float(cfg.get("zone_satisfied_low") or 68.0)
    high = float(cfg.get("zone_satisfied_high") or 76.0)
    zones_ok = pc.and_(pc.greater_equal(avg, low), pc.less_equal(avg, high))
    candidate = pc.and_(pc.and_(unoccupied, fan_on), zones_ok)
    min_samples = int(cfg.get("min_fault_samples") or 10)
    return arrow_consecutive_true(candidate, min_samples)
