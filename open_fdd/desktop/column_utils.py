"""DataFrame helpers kept free of ``services`` imports (avoids cycles with storage)."""

from __future__ import annotations

import pandas as pd


def dedupe_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy whose column labels are unique.

    Duplicate labels (e.g. from ``pd.concat`` of Feather files with overlapping headers)
    make ``df[name]`` return a DataFrame and break ``pd.to_datetime`` / merge logic with
    ``ValueError: cannot assemble with duplicate keys``.
    """
    if df.columns.is_unique:
        return df.copy()
    counts: dict[str, int] = {}
    new_cols: list[str] = []
    for c in df.columns:
        base = str(c)
        n = counts.get(base, 0)
        counts[base] = n + 1
        new_cols.append(base if n == 0 else f"{base}__{n}")
    out = df.copy()
    out.columns = new_cols
    return out
