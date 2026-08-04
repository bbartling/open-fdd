"""Trustworthy interval durations for irregular timestamps."""

from __future__ import annotations

import math

import pandas as pd

# Pass as max_gap_seconds to disable capping. None means the public default (3x nominal).
UNLIMITED_GAP_SECONDS = math.inf


def interval_durations(
    index: pd.Index,
    *,
    nominal_seconds: float,
    max_gap_seconds: float | None = None,
    final_duration_seconds: float = 0.0,
    preserve_row_order: bool = False,
) -> pd.Series:
    """Per-timestamp forward durations in seconds.

    Public default (``preserve_row_order=False``): sort, dedupe, apply gap cap,
    and set the final row to ``final_duration_seconds`` (default 0).

    When ``max_gap_seconds`` is ``None``, the cap is ``max(3 * nominal, nominal)``.
    Pass ``UNLIMITED_GAP_SECONDS`` (``math.inf``) for no upper cap — do not use
    ``None`` for that, since ``None`` selects the default 3x policy.

    Rule confirmation paths use ``preserve_row_order=True`` with
    ``UNLIMITED_GAP_SECONDS`` to keep original row order, duplicates, and
    uncapped forward deltas.
    """
    if not isinstance(index, pd.DatetimeIndex) or index.empty:
        return pd.Series(dtype=float)

    if preserve_row_order:
        working = pd.DatetimeIndex(index)
    else:
        working = pd.DatetimeIndex(index).drop_duplicates().sort_values()

    seconds = working.to_series().shift(-1).sub(working.to_series()).dt.total_seconds()
    if max_gap_seconds is None:
        cap = max(float(nominal_seconds) * 3.0, float(nominal_seconds))
    else:
        cap = float(max_gap_seconds)
    seconds = seconds.clip(lower=0.0, upper=cap)
    if len(seconds):
        seconds.iloc[-1] = max(float(final_duration_seconds), 0.0)
    return seconds.astype(float)


def hours_under_mask(
    mask: pd.Series,
    *,
    nominal_seconds: float,
    max_gap_seconds: float | None = None,
) -> float:
    normalized = mask.groupby(level=0).max().sort_index().fillna(False).astype(bool)
    durations = interval_durations(
        normalized.index,
        nominal_seconds=nominal_seconds,
        max_gap_seconds=max_gap_seconds,
    )
    return float((normalized.reindex(durations.index).astype(float) * durations).sum() / 3600.0)
