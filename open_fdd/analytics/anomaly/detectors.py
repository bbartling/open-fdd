"""SQL-portable anomaly detectors (pandas / numpy only).

Rolling Z-score and rolling MAD are written so a later DataFusion port can
reuse the same thresholds and window semantics. This module must not import
``sklearn`` or ``statsmodels``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ZSCORE_THRESHOLD = 3.0
MAD_THRESHOLD = 3.5


def samples_per_day(index: pd.DatetimeIndex) -> int:
    """Window length ≈ one day of samples from the median timestamp spacing."""
    if len(index) < 2:
        return 24
    delta_s = pd.Series(index).diff().dt.total_seconds().median()
    if delta_s is None or not np.isfinite(delta_s) or float(delta_s) <= 0:
        return 24
    return max(4, int(round(86400.0 / float(delta_s))))


def median_sample_delta(index: pd.DatetimeIndex) -> pd.Timedelta:
    """Median positive spacing between samples (fallback 5 minutes)."""
    if len(index) < 2:
        return pd.Timedelta(minutes=5)
    delta = pd.Series(index).diff().dropna().median()
    if delta is None or pd.isna(delta) or delta <= pd.Timedelta(0):
        return pd.Timedelta(minutes=5)
    return pd.Timedelta(delta)


def _numeric(y: pd.Series) -> pd.Series:
    values = pd.to_numeric(y, errors="coerce")
    values.index = y.index
    return values


def _min_periods(window: int) -> int:
    window = max(int(window), 1)
    if window < 3:
        return window
    return window


def rolling_zscore_flags(
    y: pd.Series,
    *,
    window: int,
    threshold: float = ZSCORE_THRESHOLD,
) -> pd.Series:
    """Flag samples whose trailing-window Z-score exceeds ``threshold``.

    ``|x - mean| / stddev > threshold``. A zero or missing stddev never flags
    (constant windows).
    """
    values = _numeric(y)
    span = _min_periods(window)
    mean = values.rolling(span, min_periods=span).mean()
    std = values.rolling(span, min_periods=span).std(ddof=1)
    safe_std = std.where(std > 0)
    score = (values - mean).abs() / safe_std
    flags = score.gt(float(threshold)).fillna(False)
    return flags.astype(bool)


def rolling_mad_flags(
    y: pd.Series,
    *,
    window: int,
    threshold: float = MAD_THRESHOLD,
) -> pd.Series:
    """Flag samples whose trailing-window modified deviation exceeds ``threshold``.

    Score is ``|x - median| / MAD`` with ``MAD = median(|x - median|)`` inside
    the same window. ``MAD == 0`` never flags.
    """
    values = _numeric(y)
    span = _min_periods(window)

    def _mad(win: np.ndarray) -> float:
        finite = win[np.isfinite(win)]
        if finite.size == 0:
            return np.nan
        center = float(np.median(finite))
        return float(np.median(np.abs(finite - center)))

    center = values.rolling(span, min_periods=span).median()
    mad = values.rolling(span, min_periods=span).apply(_mad, raw=True)
    safe_mad = mad.where(mad > 0)
    score = (values - center).abs() / safe_mad
    flags = score.gt(float(threshold)).fillna(False)
    return flags.astype(bool)


def dedupe_events(flags: pd.Series) -> pd.Series:
    """Keep false→true edges only. A leading True counts as an event."""
    current = flags.fillna(False).astype(bool)
    previous = current.shift(1, fill_value=False).astype(bool)
    return (current & ~previous).astype(bool)


def anomaly_minutes(flags: pd.Series, median_dt: pd.Timedelta | float) -> float:
    """Flagged sample count × median sample spacing, in minutes."""
    count = int(pd.Series(flags).fillna(False).astype(bool).sum())
    if isinstance(median_dt, pd.Timedelta):
        minutes = median_dt.total_seconds() / 60.0
    else:
        minutes = float(median_dt)
    if not np.isfinite(minutes) or minutes < 0:
        return 0.0
    return float(count * minutes)


def is_binary_like(y: pd.Series, max_unique: int = 3) -> bool:
    """True when the finite numeric series has at most ``max_unique`` distinct values."""
    numeric = _numeric(y).dropna()
    if numeric.empty:
        return True
    return int(numeric.nunique()) <= int(max_unique)
