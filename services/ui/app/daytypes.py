"""Day-type classification for WattLab diurnal dumps.

Classifies each timestamp as ``weekday``, ``weekend``, or ``holiday``.
Holidays use pandas' built-in US Federal holiday calendar and take
precedence over weekday/weekend.
"""

from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

DAY_TYPES = ("weekday", "weekend", "holiday")


def _holiday_dates(index: pd.DatetimeIndex) -> set[pd.Timestamp]:
    """Return normalized (date-only) holiday timestamps covering the index span."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return set()
    # Work in the index's own timezone when present; calendar is date-based.
    start = index.min()
    end = index.max()
    # Expand one day on each side so midnight-edge samples are covered.
    start_naive = pd.Timestamp(start).tz_localize(None) if getattr(start, "tz", None) else pd.Timestamp(start)
    end_naive = pd.Timestamp(end).tz_localize(None) if getattr(end, "tz", None) else pd.Timestamp(end)
    cal = USFederalHolidayCalendar()
    holidays = cal.holidays(start=start_naive.normalize() - pd.Timedelta(days=1), end=end_naive.normalize() + pd.Timedelta(days=1))
    return {pd.Timestamp(h).normalize() for h in holidays}


def day_type_series(index: pd.DatetimeIndex) -> pd.Series:
    """Return a Series of day_type labels aligned to ``index``.

    Holiday takes precedence over weekday/weekend. Weekends are Saturday
    and Sunday (dayofweek 5 and 6).
    """
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return pd.Series(dtype=object)
    holiday_dates = _holiday_dates(index)
    # Normalize dates in the same tz as the index for set membership.
    dates = pd.Series(index.normalize(), index=index)
    # Compare date-only (drop tz for membership against calendar dates).
    date_naive = dates.map(
        lambda t: pd.Timestamp(t).tz_localize(None).normalize()
        if getattr(t, "tz", None) is not None
        else pd.Timestamp(t).normalize()
    )
    is_holiday = date_naive.isin(holiday_dates)
    is_weekend = pd.Series(index.dayofweek >= 5, index=index)
    out = pd.Series("weekday", index=index, dtype=object)
    out = out.where(~is_weekend, "weekend")
    out = out.where(~is_holiday, "holiday")
    return out


def day_type_masks(index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Return ``{day_type: boolean mask}`` for weekday / weekend / holiday."""
    labels = day_type_series(index)
    return {dt: labels.eq(dt) for dt in DAY_TYPES}


__all__ = [
    "DAY_TYPES",
    "day_type_series",
    "day_type_masks",
]
