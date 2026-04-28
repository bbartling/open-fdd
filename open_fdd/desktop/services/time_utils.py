from __future__ import annotations

from typing import Iterable

import pandas as pd


def infer_timestamp_column(frame: pd.DataFrame, *, candidate_names: Iterable[str] | None = None) -> str:
    """
    Pick the most likely timestamp column from a frame.

    Preference order:
    1) exact "timestamp" (case-insensitive)
    2) configured candidate names
    3) first column whose name contains "time" or "date"
    4) first frame column as last resort
    """
    cols = [str(c) for c in frame.columns]
    if not cols:
        raise ValueError("Frame has no columns to infer timestamp from.")
    for c in cols:
        if c.strip().casefold() == "timestamp":
            return c
    for name in list(candidate_names or []):
        for c in cols:
            if c.strip().casefold() == str(name).strip().casefold():
                return c
    for c in cols:
        lower = c.strip().casefold()
        if "time" in lower or "date" in lower:
            return c
    return cols[0]


def parse_timestamp_series(
    frame: pd.DataFrame,
    *,
    timestamp_col: str,
    min_valid_ratio: float = 0.5,
) -> pd.Series:
    """
    Parse a timestamp column and validate minimum parse success.
    """
    parsed = pd.to_datetime(frame[timestamp_col], errors="coerce", utc=True)
    if len(parsed.index) == 0:
        raise ValueError(f"No rows available in timestamp column '{timestamp_col}'.")
    valid_ratio = float(parsed.notna().mean())
    if valid_ratio < max(0.01, min(1.0, min_valid_ratio)):
        sample_cols = ", ".join([str(c) for c in frame.columns[:10]])
        raise ValueError(
            f"No valid timestamp column found. Candidate '{timestamp_col}' parse ratio={valid_ratio:.2f}. "
            f"Available columns: {sample_cols}"
        )
    return parsed
