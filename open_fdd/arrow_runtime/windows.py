"""Arrow-native time/window helpers — batch-oriented, no pandas."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .arrays import as_array


def arrow_shift(array: pa.Array | pa.ChunkedArray, periods: int = 1) -> pa.ChunkedArray:
    """Previous-value shift (positive periods = lag)."""
    if periods <= 0:
        return as_array(array)
    flat = as_array(array)
    n = len(flat)
    if n == 0:
        return flat
    nulls = pa.nulls(periods, type=flat.type)
    head = flat.slice(0, max(0, n - periods))
    return pa.concat_arrays([nulls, head])


def arrow_diff(array: pa.Array | pa.ChunkedArray, periods: int = 1) -> pa.ChunkedArray:
    prev = arrow_shift(array, periods)
    cur = as_array(array)
    return pc.subtract(pc.cast(cur, pa.float64()), pc.cast(prev, pa.float64()))


def arrow_abs_diff(array: pa.Array | pa.ChunkedArray, periods: int = 1) -> pa.ChunkedArray:
    return pc.abs(arrow_diff(array, periods))


def arrow_consecutive_true(mask: pa.Array | pa.ChunkedArray, n: int) -> pa.ChunkedArray:
    """True when at least ``n`` consecutive prior samples (inclusive) are true."""
    if n <= 1:
        return as_array(mask)
    m = as_array(mask).cast(pa.bool_())
    count = m.cast(pa.int32())
    for _ in range(1, n):
        prev = arrow_shift(count, 1).fill_null(0)
        count = pc.add(count, prev)
    return pc.greater_equal(count, n)


def arrow_rolling_min(array: pa.Array | pa.ChunkedArray, window: int) -> pa.ChunkedArray:
    """Fixed-window rolling min over batches (Python orchestration, not per-row rules)."""
    flat = pc.cast(as_array(array), pa.float64())
    n = len(flat)
    if window <= 1 or n == 0:
        return flat
    out: list[Any] = []
    for i in range(n):
        start = max(0, i - window + 1)
        chunk = flat.slice(start, i - start + 1)
        out.append(pc.min(chunk).as_py())
    return pa.array(out, type=pa.float64())


def arrow_rolling_max(array: pa.Array | pa.ChunkedArray, window: int) -> pa.ChunkedArray:
    flat = pc.cast(as_array(array), pa.float64())
    n = len(flat)
    if window <= 1 or n == 0:
        return flat
    out: list[Any] = []
    for i in range(n):
        start = max(0, i - window + 1)
        chunk = flat.slice(start, i - start + 1)
        out.append(pc.max(chunk).as_py())
    return pa.array(out, type=pa.float64())


def arrow_flatline_check(array: pa.Array | pa.ChunkedArray, window: int, epsilon: float = 1e-6) -> pa.ChunkedArray:
    """True when rolling max-min <= epsilon over ``window`` samples."""
    rmin = arrow_rolling_min(array, window)
    rmax = arrow_rolling_max(array, window)
    spread = pc.subtract(rmax, rmin)
    return pc.less_equal(pc.abs(spread), epsilon)


def arrow_time_delta_seconds(ts: pa.Array | pa.ChunkedArray) -> pa.ChunkedArray:
    cur = pc.cast(as_array(ts), pa.timestamp("us", tz="UTC"))
    prev = arrow_shift(cur, 1)
    delta = pc.subtract(cur, prev)
    return pc.cast(delta, pa.duration("s"))


def arrow_rate_of_change(value: pa.Array | pa.ChunkedArray, ts: pa.Array | pa.ChunkedArray) -> pa.ChunkedArray:
    dv = arrow_diff(value, 1)
    dt = arrow_time_delta_seconds(ts)
    secs = pc.cast(dt, pa.int64())
    safe = pc.if_else(pc.equal(secs, 0), pa.scalar(None, pa.float64()), pc.divide(dv, pc.cast(secs, pa.float64())))
    return safe


def arrow_paint_lookback(mask: pa.Array | pa.ChunkedArray, lookback: int) -> pa.ChunkedArray:
    """Retroactively mark prior ``lookback`` samples when mask is true."""
    m = as_array(mask).cast(pa.bool_())
    n = len(m)
    if lookback <= 0 or n == 0:
        return m
    out = [False] * n
    for i in range(n):
        if m[i].as_py():
            start = max(0, i - lookback + 1)
            for j in range(start, i + 1):
                out[j] = True
    return pa.array(out, type=pa.bool_())
