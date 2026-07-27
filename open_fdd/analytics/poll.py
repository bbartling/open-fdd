"""Polling / interval helpers shared by analytics."""

from __future__ import annotations

import pandas as pd


def infer_poll_seconds(df: pd.DataFrame) -> float:
    if not isinstance(df.index, pd.DatetimeIndex) or len(df.index) < 2:
        return 300.0
    deltas = df.index.to_series().diff().dropna().dt.total_seconds()
    if deltas.empty:
        return 300.0
    med = float(deltas.median())
    return med if med > 0 else 300.0
