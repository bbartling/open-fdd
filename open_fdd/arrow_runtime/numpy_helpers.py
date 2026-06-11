"""Optional NumPy helpers for advanced analytics — not required for core cookbook rules."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .arrays import as_array


def _require_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "NumPy is required for this helper. Install with: pip install 'open-fdd[analytics]'"
        ) from exc
    return np


def rolling_mean(array: pa.Array | pa.ChunkedArray, window: int) -> pa.Array:
    """Rolling mean via NumPy (optional). Converts back to PyArrow float64 array."""
    np = _require_numpy()
    if window <= 1:
        return pc.cast(as_array(array), pa.float64())
    flat = as_array(array).to_numpy(zero_copy_only=False)
    out = np.full(len(flat), np.nan, dtype=float)
    for i in range(len(flat)):
        start = max(0, i - window + 1)
        chunk = flat[start : i + 1]
        if len(chunk):
            out[i] = float(np.nanmean(chunk))
    return pa.array(out, type=pa.float64())


def pearson_correlation(
    x: pa.Array | pa.ChunkedArray,
    y: pa.Array | pa.ChunkedArray,
) -> float | None:
    """Pearson r between two series (ignores NaN pairs). Returns None if undefined."""
    np = _require_numpy()
    xs = as_array(x).to_numpy(zero_copy_only=False).astype(float)
    ys = as_array(y).to_numpy(zero_copy_only=False).astype(float)
    mask = ~(np.isnan(xs) | np.isnan(ys))
    if mask.sum() < 2:
        return None
    r = float(np.corrcoef(xs[mask], ys[mask])[0, 1])
    return r

