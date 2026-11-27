"""#1642: the pandas runner joins web weather as-of, as the SQL rules do (latest non-null reading at or before the
sample, at most WEB_CADENCE_SECONDS + WEB_ASOF_MARGIN_SECONDS old)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from open_fdd.rules.runner import WEB_ASOF_BOUND_SECONDS, _weather_asof, merge_weather

ROOT = Path(__file__).resolve().parents[1]
T0 = pd.Timestamp("2026-05-04", tz="UTC")


def test_bound_matches_the_sql_runtime_defaults():
    d = json.loads((ROOT / "sql" / "fdd" / "runtime_defaults.json").read_text(encoding="utf-8"))
    assert WEB_ASOF_BOUND_SECONDS == d["WEB_CADENCE_SECONDS"] + d["WEB_ASOF_MARGIN_SECONDS"] == 1500.0


def test_latest_at_or_before_within_the_bound_per_column():
    wx = pd.DataFrame({"weather_service_air_temperature": [10.0, np.nan, 12.0], "weather_service_air_dew_point_temperature": [5.0, 6.0, np.nan]},
                      index=[T0, T0 + pd.Timedelta(minutes=20), T0 + pd.Timedelta(minutes=40)])
    idx = pd.DatetimeIndex([T0 - pd.Timedelta(minutes=1), T0 + pd.Timedelta(seconds=37), T0 + pd.Timedelta(minutes=25),
                            T0 + pd.Timedelta(minutes=41), T0 + pd.Timedelta(minutes=66)])
    got = _weather_asof(wx, idx)
    # before the first reading: none; jittered rows take the reading at or before them; dewpoint skips its NaN
    assert np.isnan(got["weather_service_air_temperature"].iloc[0])
    assert got["weather_service_air_temperature"].iloc[3] == 12.0
    assert got["weather_service_air_temperature"].iloc[1] == 10.0 and got["weather_service_air_temperature"].iloc[2] == 10.0
    assert got["weather_service_air_dew_point_temperature"].iloc[2] == 6.0 and got["weather_service_air_dew_point_temperature"].iloc[3] == 6.0
    # 66 min is 26 min after the last temperature reading: older than the 25 min bound, so unknown
    assert np.isnan(got["weather_service_air_temperature"].iloc[4])


def test_bound_is_inclusive_and_exact_matches_are_kept():
    wx = pd.DataFrame({"weather_service_air_temperature": [10.0]}, index=[T0])
    idx = pd.DatetimeIndex([T0, T0 + pd.Timedelta(seconds=1500), T0 + pd.Timedelta(seconds=1501)])
    assert _weather_asof(wx, idx)["weather_service_air_temperature"].tolist()[:2] == [10.0, 10.0]
    assert np.isnan(_weather_asof(wx, idx)["weather_service_air_temperature"].iloc[2])


def test_merge_weather_fills_a_jittered_equipment_frame():
    wx = pd.DataFrame({"weather_service_air_temperature": [10.0, 11.0]}, index=[T0, T0 + pd.Timedelta(minutes=20)])
    eq = pd.DataFrame({"discharge_air_temperature": [13.0, 13.1, 13.2]},
                      index=[T0 + pd.Timedelta(seconds=17), T0 + pd.Timedelta(minutes=5, seconds=3), T0 + pd.Timedelta(minutes=21)])
    out = merge_weather(eq, wx)
    assert out["weather_service_air_temperature"].tolist() == [10.0, 10.0, 11.0]   # an exact-timestamp join gave three NaN
