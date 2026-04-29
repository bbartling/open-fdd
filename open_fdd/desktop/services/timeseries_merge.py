"""
Merge time-series frames from multiple drivers (CSV, weather, onboard, BACnet, …)
on a shared timestamp. Used on read — no persisted merged Feather artifact.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from open_fdd.desktop.services.time_utils import infer_timestamp_column

# Typical driver `source` tags used with FeatherStore / ingest. Future drivers use
# their own string tag; merge accepts any non-empty source name the connector knows.
DEFAULT_SITE_DRIVER_SOURCES: tuple[str, ...] = ("csv", "weather", "onboard", "bacnet")


def merge_site_frames_on_timestamp(
    parts: Iterable[tuple[str, pd.DataFrame]],
    *,
    join_how: str = "outer",
    timestamp_col: str = "timestamp",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Outer-join (by default) multiple site frames on ``timestamp``.

    Parameters
    ----------
    parts:
        ``(source_tag, frame)`` pairs. ``source_tag`` is the ingest driver key
        (e.g. ``\"csv\"``, ``\"weather\"``) and is used to disambiguate metric columns
        when more than one frame is merged: ``metric`` → ``metric_<source_tag>``.
    join_how:
        Pandas merge how: ``outer`` | ``left`` | ``inner`` | ``right``.
    timestamp_col:
        Unified timestamp column name in the result.

    Returns
    -------
    Sorted frame on ``timestamp_col`` and the list of source tags that contributed rows.
    Empty frame if every input frame is empty.
    """
    pairs = [(str(s).strip(), f.copy()) for s, f in parts if str(s).strip() and f is not None]
    non_empty = [(s, f) for s, f in pairs if not f.empty]
    if not non_empty:
        return pd.DataFrame(), []

    if len(non_empty) == 1:
        src, df = non_empty[0]
        tc = infer_timestamp_column(df)
        if tc != timestamp_col and tc in df.columns:
            df = df.rename(columns={tc: timestamp_col})
        out = df.sort_values(timestamp_col).reset_index(drop=True)
        return out, [src]

    how = join_how if join_how in ("inner", "left", "outer", "right") else "outer"
    merged: pd.DataFrame | None = None
    for src, df in non_empty:
        work = df.copy()
        tc = infer_timestamp_column(work)
        if tc != timestamp_col:
            work = work.rename(columns={tc: timestamp_col})
        work[timestamp_col] = pd.to_datetime(work[timestamp_col], utc=True, errors="coerce")
        work = work[work[timestamp_col].notna()].copy()
        rename_map = {c: f"{c}_{src}" for c in work.columns if c != timestamp_col}
        work = work.rename(columns=rename_map)
        if merged is None:
            merged = work
        else:
            merged = merged.merge(work, on=timestamp_col, how=how)
    assert merged is not None
    out = merged.sort_values(timestamp_col).reset_index(drop=True)
    used = [s for s, _ in non_empty]
    return out, used
