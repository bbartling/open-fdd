"""
Time-of-week and weather-band masks for expression rules.

These inject boolean Series into the expression namespace as ``schedule_occupied`` and
``weather_allows_fdd`` when ``params.schedule`` / ``params.weather_band`` are set.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def datetime_series_for_rows(
    df: pd.DataFrame, timestamp_col: Optional[str] = None
) -> pd.Series:
    """
    Return one timestamp per row, aligned with ``df.index``.

    Requires either a :class:`pandas.DatetimeIndex` on ``df`` or a parseable
    ``timestamp`` / ``timestamp_col`` column.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(df.index, index=df.index)
    col = timestamp_col
    if col is None and "timestamp" in df.columns:
        col = "timestamp"
    if col and col in df.columns:
        return pd.to_datetime(df[col], utc=False)
    raise ValueError(
        "Schedule gates require a DatetimeIndex on the DataFrame or a timestamp column "
        "(e.g. 'timestamp'). Pass timestamp_col=... to RuleRunner.run() if needed."
    )


def weekly_occupied_mask(
    dt: pd.Series,
    weekdays: List[int],
    start_hour: int,
    end_hour: int,
) -> pd.Series:
    """
    True where local time falls on one of ``weekdays`` (Mon=0 … Sun=6) and
    ``start_hour <= hour < end_hour`` (0–23).

    Example: weekdays Mon–Fri, 8:00–17:00 → ``[0,1,2,3,4]``, ``start_hour=8``,
    ``end_hour=17`` (last included minute is 16:59).
    """
    ts = pd.to_datetime(dt)
    w = ts.dt.weekday
    h = ts.dt.hour
    return w.isin(weekdays) & (h >= start_hour) & (h < end_hour)


def weather_allows_fdd_mask(
    oat: pd.Series,
    low: float,
    high: float,
) -> pd.Series:
    """
    True where outside-air temperature is inside ``[low, high]`` (inclusive) and not NaN.

    When False, the row is outside the analysis band (e.g. extreme cold/heat); combine
    with ``& weather_allows_fdd`` so faults are suppressed during extremes.
    """
    return oat.notna() & (oat >= low) & (oat <= high)


def build_schedule_weather_namespace(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    params: Dict[str, Any],
    timestamp_col: Optional[str] = None,
) -> Dict[str, pd.Series]:
    """
    Build ``schedule_occupied`` and ``weather_allows_fdd`` Series for expression eval.

    Defaults: both are all-True (no gating) unless ``params['schedule']`` or
    ``params['weather_band']`` are set with ``enabled`` not False.
    """
    idx = df.index
    out: Dict[str, pd.Series] = {
        "schedule_occupied": pd.Series(True, index=idx),
        "weather_allows_fdd": pd.Series(True, index=idx),
    }

    sched = params.get("schedule")
    if isinstance(sched, dict) and sched.get("enabled", True) is not False:
        dt = datetime_series_for_rows(df, timestamp_col)
        weekdays = list(sched.get("weekdays", [0, 1, 2, 3, 4]))
        start_hour = int(sched.get("start_hour", 8))
        end_hour = int(sched.get("end_hour", 17))
        out["schedule_occupied"] = weekly_occupied_mask(
            dt, weekdays=weekdays, start_hour=start_hour, end_hour=end_hour
        )

    wb = params.get("weather_band")
    if isinstance(wb, dict) and wb.get("enabled", True) is not False:
        oat_key = wb.get("oat_input", "Outside_Air_Temperature_Sensor")
        col = col_map.get(oat_key)
        if not col or col not in df.columns:
            raise ValueError(
                f"weather_band requires rule input '{oat_key}' mapped to a column "
                f"(found col_map={col!r})."
            )
        units = str(wb.get("units", "imperial")).lower()
        low = float(wb.get("low", 32))
        high = float(wb.get("high", 85))
        if units == "metric":
            # low/high are °C
            pass
        elif units == "imperial":
            # low/high are °F
            pass
        else:
            raise ValueError("weather_band.units must be 'imperial' or 'metric'")
        oat = df[col]
        out["weather_allows_fdd"] = weather_allows_fdd_mask(oat, low, high)

    return out


def params_for_expression_eval(params: Dict[str, Any]) -> Dict[str, Any]:
    """Strip nested dicts that are not valid eval scalars."""
    skip = {"schedule", "weather_band"}
    return {k: v for k, v in params.items() if k not in skip}
