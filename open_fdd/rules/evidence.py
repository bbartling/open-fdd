"""Compact JSON-safe evidence. Never serialize a pandas repr (no ellipses)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd



class UnsafeEvidenceError(TypeError):
    """Raised when a value cannot be serialized without str()."""


def _ts(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return str(pd.Timestamp(value))


def _hours_true(mask: pd.Series, poll_seconds: float) -> float:
    from open_fdd.rules.base import hours_true

    return hours_true(mask, poll_seconds)


def sparse_intervals(mask: pd.Series, *, poll_seconds: float = 300.0) -> list[dict[str, Any]]:
    m = mask.fillna(False).astype(bool)
    if not m.any():
        return []
    groups = (m != m.shift()).cumsum()
    out: list[dict[str, Any]] = []
    for _, g in m[m].groupby(groups):
        out.append(
            {
                "first": _ts(g.index[0]),
                "last": _ts(g.index[-1]),
                "count": int(len(g)),
                "duration": round(_hours_true(g.reindex(m.index).fillna(False), poll_seconds), 4),
            }
        )
    return out


def series_summary(
    series: pd.Series,
    *,
    role: str,
    valid: pd.Series | None = None,
    poll_seconds: float = 300.0,
) -> dict[str, Any]:
    num = pd.to_numeric(series, errors="coerce")
    ok = valid if valid is not None else num.notna()
    ok = ok.reindex(series.index).fillna(False).astype(bool)
    sample = num[ok]
    first = last = None
    if ok.any() and isinstance(series.index, pd.DatetimeIndex):
        idx = series.index[ok]
        first, last = _ts(idx[0]), _ts(idx[-1])
    stats: dict[str, Any] = {
        "min": None,
        "max": None,
        "median": None,
    }
    if len(sample):
        stats["min"] = float(sample.min())
        stats["max"] = float(sample.max())
        stats["median"] = float(sample.median())
    return {
        "role": role,
        "count": int(ok.sum()),
        "duration": round(_hours_true(ok, poll_seconds), 4),
        "first": first,
        "last": last,
        "min": stats["min"],
        "max": stats["max"],
        "median": stats["median"],
        "valid_coverage": round(float(ok.mean()) if len(ok) else 0.0, 4),
    }


def json_safe(value: Any, *, poll_seconds: float = 300.0, role: str = "") -> Any:
    """Convert metrics to JSON primitives. Rejects pandas objects via summaries."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, np.generic):
        return json_safe(value.item(), poll_seconds=poll_seconds, role=role)
    if isinstance(value, pd.Timestamp):
        return str(value)
    if isinstance(value, pd.Series):
        name = role or str(value.name or "series")
        if value.dtype == bool or set(pd.unique(value.dropna().astype(str))) <= {"0", "1", "True", "False", "true", "false"}:
            summary = series_summary(value.astype(float), role=name, poll_seconds=poll_seconds)
            summary["fault_intervals"] = sparse_intervals(value.fillna(False).astype(bool), poll_seconds=poll_seconds)
            return summary
        return series_summary(value, role=name, poll_seconds=poll_seconds)
    if isinstance(value, pd.DataFrame):
        return {
            "columns": [str(c) for c in value.columns],
            "rows": int(len(value)),
        }
    if isinstance(value, dict):
        return {str(k): json_safe(v, poll_seconds=poll_seconds, role=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v, poll_seconds=poll_seconds, role=role) for v in value]
    raise UnsafeEvidenceError(f"cannot serialize {type(value).__name__} without str()")


def assert_no_pandas_repr(blob: str) -> None:
    if "..." in blob or "dtype:" in blob or "Length:" in blob:
        raise AssertionError("pandas repr leaked into JSON evidence")
