"""
Best-effort coercion of Grafana-style string metrics (``17.8 psi``, ``69.5 °F``, ``100 %``) to floats.

Used for agent/human data prep before BRICK mapping and FDD rules that expect numeric frames.
"""

from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import pandas as pd

from open_fdd.desktop.services.time_utils import infer_timestamp_column

# Leading signed decimal; trailing unit text is ignored.
_NUMERIC_LEAD = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][-+]?\d+)?)\s*")


def _parse_scalar_to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, np.integer)):
        return float(int(value))
    if isinstance(value, (float, np.floating)):
        v = float(value)
        return None if np.isnan(v) else v
    text = str(value).strip()
    if not text:
        return None
    low = text.casefold()
    if low in ("true", "t", "yes", "on"):
        return 1.0
    if low in ("false", "f", "no", "off"):
        return 0.0
    m = _NUMERIC_LEAD.match(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def suggest_coercible_columns(frame: pd.DataFrame, *, min_ratio: float = 0.35, sample: int = 800) -> list[str]:
    """Columns where a leading numeric parse succeeds for at least ``min_ratio`` of sampled non-null cells."""
    if frame.empty:
        return []
    ts = "timestamp" if "timestamp" in frame.columns else infer_timestamp_column(frame)
    names: list[str] = []
    for col in frame.columns:
        if str(col) == ts:
            continue
        s = frame[col]
        if pd.api.types.is_bool_dtype(s):
            continue
        if pd.api.types.is_numeric_dtype(s):
            continue
        ser = s.dropna()
        if ser.empty:
            continue
        chunk = ser.head(sample)
        ok = sum(1 for v in chunk if _parse_scalar_to_float(v) is not None)
        if ok / max(len(chunk), 1) >= min_ratio:
            names.append(str(col))
    return names


def coerce_metrics_to_numeric(
    frame: pd.DataFrame,
    *,
    columns: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Coerce selected columns from strings-with-units to float. Booleans become int 0/1 for stable Feather/JSON.
    """
    out = frame.copy()
    stats: dict[str, Any] = {}
    ts = "timestamp" if "timestamp" in out.columns else infer_timestamp_column(out)
    for col in list(out.columns):
        if str(col) == ts:
            continue
        if col not in columns:
            continue
        s = out[col]
        if pd.api.types.is_bool_dtype(s):
            out[col] = s.astype("int8")
            stats[str(col)] = {"kind": "bool_to_int8"}
            continue
        if pd.api.types.is_numeric_dtype(s):
            stats[str(col)] = {"kind": "already_numeric"}
            continue
        parsed = s.map(_parse_scalar_to_float)
        num = pd.to_numeric(parsed, errors="coerce")
        ratio = float(num.notna().mean()) if len(s) else 0.0
        out[col] = num
        stats[str(col)] = {"kind": "string_to_float", "non_null_numeric_ratio": ratio}
    return out, stats


def preview_rows_json(frame: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    view = frame.head(n).copy()
    view = view.where(pd.notnull(view), None)
    if "timestamp" in view.columns:
        view = view.copy()
        view["timestamp"] = view["timestamp"].astype(str)
    blob = view.to_json(orient="records", date_format="iso", double_precision=15)
    return json.loads(blob) if blob else []
