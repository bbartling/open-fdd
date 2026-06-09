"""Reusable Arrow-native rule primitives (Grade-A building blocks)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.playground.cookbook import cfg_threshold

from .cookbook import (
    arrow_rolling_mean,
    flatline_1h_mask,
    mixing_envelope_mask,
    oob_mask,
    rate_of_change_mask,
    sensor_bounds_mask,
    sensor_flatline_mask,
    value_column,
)
from .windows import arrow_consecutive_true


def threshold_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    col: str | None = None,
    op: str = "gt",
) -> pa.ChunkedArray:
    name = value_column(table, cfg, col)
    vals = pc.cast(table[name], pa.float64())
    limit = cfg_threshold(cfg, str(cfg.get("threshold_key") or "threshold"))
    if op == "lt":
        return pc.less(vals, limit)
    if op == "ge":
        return pc.greater_equal(vals, limit)
    if op == "le":
        return pc.less_equal(vals, limit)
    return pc.greater(vals, limit)


def range_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    col: str | None = None,
    low_key: str = "bounds_low",
    high_key: str = "bounds_high",
) -> pa.ChunkedArray:
    return oob_mask(table, {**cfg, "bounds_low": cfg.get(low_key), "bounds_high": cfg.get(high_key)}, col=col)


def deadband_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    value_col: str,
    setpoint_col: str,
    deadband_key: str = "deadband",
) -> pa.ChunkedArray:
    """True when |value - setpoint| exceeds deadband."""
    if value_col not in table.column_names or setpoint_col not in table.column_names:
        n = table.num_rows
        return pa.array([False] * n, type=pa.bool_())
    val = pc.cast(table[value_col], pa.float64())
    sp = pc.cast(table[setpoint_col], pa.float64())
    band = cfg_threshold(cfg, deadband_key)
    err = pc.abs(pc.subtract(val, sp))
    return pc.greater(err, band)


def persistence_mask(mask: pa.Array | pa.ChunkedArray, min_samples: int) -> pa.ChunkedArray:
    """True when condition holds for ``min_samples`` consecutive rows."""
    return arrow_consecutive_true(mask, max(1, int(min_samples)))


def rolling_percent_true_arrow(mask: pa.Array | pa.ChunkedArray, window: int) -> pa.ChunkedArray:
    """Fraction of True in rolling window (0–1)."""
    flat = mask.cast(pa.float64())
    return arrow_rolling_mean(flat, max(1, int(window)))


def command_feedback_mismatch(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    command_col: str,
    feedback_col: str,
    tolerance_key: str = "cmd_fb_tolerance",
) -> pa.ChunkedArray:
    if command_col not in table.column_names or feedback_col not in table.column_names:
        n = table.num_rows
        return pa.array([False] * n, type=pa.bool_())
    cmd = pc.cast(table[command_col], pa.float64())
    fb = pc.cast(table[feedback_col], pa.float64())
    tol = cfg_threshold(cfg, tolerance_key)
    return pc.greater(pc.abs(pc.subtract(cmd, fb)), tol)


def setpoint_tracking_error(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    value_col: str,
    setpoint_col: str,
    deadband_key: str = "tracking_deadband",
) -> pa.ChunkedArray:
    return deadband_mask(
        table,
        {**cfg, "deadband": cfg.get(deadband_key)},
        value_col=value_col,
        setpoint_col=setpoint_col,
        deadband_key="deadband",
    )


def simultaneous_heat_cool_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    heat_col: str,
    cool_col: str,
    on_key: str = "valve_on_min",
) -> pa.ChunkedArray:
    if heat_col not in table.column_names or cool_col not in table.column_names:
        n = table.num_rows
        return pa.array([False] * n, type=pa.bool_())
    on_min = cfg_threshold(cfg, on_key)
    heat = pc.greater(pc.cast(table[heat_col], pa.float64()), on_min)
    cool = pc.greater(pc.cast(table[cool_col], pa.float64()), on_min)
    return pc.and_(heat, cool)


def low_delta_t_mask(
    table: pa.Table,
    cfg: dict[str, Any],
    *,
    supply_col: str,
    return_col: str,
    min_delta_key: str = "min_delta_t",
) -> pa.ChunkedArray:
    if supply_col not in table.column_names or return_col not in table.column_names:
        n = table.num_rows
        return pa.array([False] * n, type=pa.bool_())
    sup = pc.cast(table[supply_col], pa.float64())
    ret = pc.cast(table[return_col], pa.float64())
    delta = pc.abs(pc.subtract(ret, sup))
    return pc.less(delta, cfg_threshold(cfg, min_delta_key))


# Re-export catalog-backed sensor masks for template convenience
flatline_mask = sensor_flatline_mask
stale_mask = flatline_mask  # stale uses separate poll metadata — alias for template id only

__all__ = [
    "threshold_mask",
    "range_mask",
    "deadband_mask",
    "persistence_mask",
    "rolling_percent_true_arrow",
    "command_feedback_mismatch",
    "setpoint_tracking_error",
    "simultaneous_heat_cool_mask",
    "low_delta_t_mask",
    "flatline_mask",
    "mixing_envelope_mask",
    "rate_of_change_mask",
    "sensor_bounds_mask",
    "persistence_mask",
]
