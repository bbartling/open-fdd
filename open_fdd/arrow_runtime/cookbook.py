"""Arrow-native FDD cookbook — flatline, spread, OOB, schedule faults (PyArrow only)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.playground.cookbook import cfg_threshold

from .windows import (
    arrow_abs_diff,
    arrow_consecutive_true,
    arrow_rolling_max,
    arrow_rolling_min,
)

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


def flatline_window_samples(cfg: dict[str, Any]) -> int:
    """Rolling window in samples for ~flatline_minutes at poll_interval_s (Acme 60s poll → 60 samples/h)."""
    if cfg.get("flatline_window_samples") is not None:
        return max(2, int(cfg["flatline_window_samples"]))
    if cfg.get("poll_interval_s") or cfg.get("median_poll_interval_s"):
        interval_s = max(30, int(cfg.get("poll_interval_s") or cfg.get("median_poll_interval_s") or 60))
        minutes = float(cfg.get("flatline_minutes") if cfg.get("flatline_minutes") is not None else 60)
        return max(2, int(round(minutes * 60.0 / interval_s)))
    if cfg.get("window_samples") is not None:
        return max(2, int(cfg["window_samples"]))
    return 12


def _window_samples(cfg: dict[str, Any]) -> int:
    return flatline_window_samples(cfg)


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
        if hasattr(val, "to_pydatetime"):
            val = val.to_pydatetime()
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


def rate_of_change_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    col: str | None = None,
    periods: int = 1,
) -> pa.ChunkedArray:
    """True when |Δvalue| between consecutive samples exceeds cfg max (per-step)."""
    name = value_column(table, cfg, col)
    vals = pc.cast(table[name], pa.float64())
    delta = arrow_abs_diff(vals, periods)
    limit = cfg_threshold(cfg, "max_per_sample")
    if "max_per_15min" in cfg and cfg.get("max_per_15min") is not None:
        limit = cfg_threshold(cfg, "max_per_15min")
    elif "max_per_hour" in cfg and cfg.get("max_per_hour") is not None:
        if cfg.get("samples_per_hour"):
            samples_per_hour = max(1, int(cfg["samples_per_hour"]))
        else:
            interval_s = max(30, int(cfg.get("poll_interval_s") or cfg.get("median_poll_interval_s") or 60))
            samples_per_hour = max(1, int(round(3600.0 / interval_s)))
        limit = cfg_threshold(cfg, "max_per_hour") / float(samples_per_hour)
    return pc.greater(delta, limit)


def mixing_envelope_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    mat_col: str = "mixed_air_temp",
    oat_col: str = "outside_air_temp",
    rat_col: str = "return_air_temp",
    fan_col: str | None = "supply_fan_speed_command",
) -> pa.ChunkedArray:
    """True when MAT is outside OAT–RAT envelope (± tolerance) while fan is on."""
    tol = float(cfg.get("mixing_tol") or cfg.get("blend_tol") or 1.15)
    fan_thresh = float(cfg.get("fan_on_threshold") or 0.01)
    mat = pc.cast(table[mat_col], pa.float64())
    oat = pc.cast(table[oat_col], pa.float64())
    rat = pc.cast(table[rat_col], pa.float64())
    oat_rat_lo = pc.if_else(pc.less(oat, rat), oat, rat)
    oat_rat_hi = pc.if_else(pc.greater(oat, rat), oat, rat)
    lo = pc.subtract(oat_rat_lo, tol)
    hi = pc.add(oat_rat_hi, tol)
    outside = pc.or_(pc.less(mat, lo), pc.greater(mat, hi))
    if fan_col and fan_col in table.column_names:
        fan = pc.cast(table[fan_col], pa.float64())
        if float(cfg.get("normalize_cmd_percent") or 0):
            fan = pc.if_else(pc.greater(fan, 1.0), pc.divide(fan, 100.0), fan)
        return pc.and_(outside, pc.greater(fan, fan_thresh))
    return outside


def sensor_bounds_mask(table: pa.Table, kind: str, cfg: dict[str, Any] | None = None) -> pa.ChunkedArray:
    """OOB mask using :mod:`sensor_catalog` defaults merged with ``cfg``."""
    from .sensor_catalog import cfg_from_profile

    merged = cfg_from_profile(kind, cfg)
    return oob_mask(table, merged)


def sensor_flatline_mask(table: pa.Table, kind: str, cfg: dict[str, Any] | None = None) -> pa.ChunkedArray:
    """Flatline mask using :mod:`sensor_catalog` defaults merged with ``cfg``."""
    from .sensor_catalog import cfg_from_profile

    merged = cfg_from_profile(kind, cfg)
    return flatline_1h_mask(table, merged)


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
