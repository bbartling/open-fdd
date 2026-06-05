"""Arrow-native feature preparation — no pandas/NumPy in this module."""

from __future__ import annotations

from typing import Any, Literal

import pyarrow as pa
import pyarrow.compute as pc


def arrow_select_columns(table: pa.Table, columns: list[str]) -> pa.Table:
    keep = [c for c in columns if c in table.column_names]
    return table.select(keep) if keep else table


def arrow_append_column(table: pa.Table, name: str, array: pa.Array | pa.ChunkedArray) -> pa.Table:
    return table.append_column(name, array)


def arrow_cast_numeric(table: pa.Table, columns: list[str]) -> pa.Table:
    out_cols: list[pa.ChunkedArray] = []
    names: list[str] = []
    for name in table.column_names:
        col = table[name]
        if name in columns:
            try:
                col = pc.cast(col, pa.float64())
            except Exception:
                pass
        out_cols.append(col)
        names.append(name)
    return pa.table(out_cols, names=names)


def arrow_fill_null(table: pa.Table, column: str, value: float) -> pa.Table:
    if column not in table.column_names:
        return table
    filled = pc.fill_null(table[column], value)
    idx = table.column_names.index(column)
    cols = list(table.columns)
    cols[idx] = filled
    return pa.table(cols, names=table.column_names)


def arrow_normalize_command(
    table: pa.Table,
    column: str,
    *,
    min_value: float = 0.0,
    max_value: float = 100.0,
) -> pa.Table:
    if column not in table.column_names:
        return table
    col = pc.cast(table[column], pa.float64())
    span = max_value - min_value
    if span <= 0:
        norm = col
    else:
        norm = pc.divide(pc.subtract(col, min_value), span)
    return arrow_append_column(table, f"{column}_norm", norm)


def arrow_boolean_mask(table: pa.Table, column: str) -> pa.ChunkedArray:
    if column not in table.column_names:
        raise KeyError(f"column not found: {column}")
    col = table[column]
    if pa.types.is_boolean(col.type):
        return col
    return pc.greater(pc.cast(col, pa.float64()), 0.0)


def arrow_time_filter(
    table: pa.Table,
    ts_column: str,
    start: Any | None,
    end: Any | None,
) -> pa.Table:
    if ts_column not in table.column_names or (start is None and end is None):
        return table
    ts = pc.cast(table[ts_column], pa.timestamp("us", tz="UTC"))
    mask = None
    if start is not None:
        start_ts = pa.scalar(start, type=pa.timestamp("us", tz="UTC"))
        m = pc.greater_equal(ts, start_ts)
        mask = m if mask is None else pc.and_(mask, m)
    if end is not None:
        end_ts = pa.scalar(end, type=pa.timestamp("us", tz="UTC"))
        m = pc.less_equal(ts, end_ts)
        mask = m if mask is None else pc.and_(mask, m)
    if mask is None:
        return table
    return table.filter(mask)


def arrow_site_filter(table: pa.Table, site_id: str, column: str = "site_id") -> pa.Table:
    if column not in table.column_names or not site_id:
        return table
    mask = pc.equal(table[column], site_id)
    return table.filter(mask)


def arrow_equipment_filter(table: pa.Table, equip_id: str, column: str = "equipment_id") -> pa.Table:
    if column not in table.column_names or not equip_id:
        return table
    mask = pc.equal(table[column], equip_id)
    return table.filter(mask)


def arrow_safe_compare(
    left: pa.Array | pa.ChunkedArray,
    op: Literal["lt", "le", "gt", "ge", "eq", "ne"],
    right: pa.Array | pa.ChunkedArray | float | int,
) -> pa.ChunkedArray:
    if not isinstance(right, (pa.Array, pa.ChunkedArray)):
        right = pa.scalar(right)
    ops = {
        "lt": pc.less,
        "le": pc.less_equal,
        "gt": pc.greater,
        "ge": pc.greater_equal,
        "eq": pc.equal,
        "ne": pc.not_equal,
    }
    fn = ops[op]
    return fn(left, right)


def arrow_fault_mask_to_column(mask: pa.Array | pa.ChunkedArray, name: str = "fault") -> pa.ChunkedArray:
    if not pa.types.is_boolean(mask.type):
        raise TypeError(f"fault mask must be boolean, got {mask.type}")
    return pc.if_else(mask, pa.scalar(1, pa.int8()), pa.scalar(0, pa.int8())).combine_chunks().cast(pa.int8())
