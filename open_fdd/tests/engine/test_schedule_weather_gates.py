"""Tests for schedule_occupied / weather_allows_fdd expression injection."""

import pandas as pd
import pytest

from open_fdd.engine.checks import check_expression
from open_fdd.engine.schedule_masks import (
    datetime_series_for_rows,
    weekly_occupied_mask,
    weather_allows_fdd_mask,
)


def test_weekly_occupied_monday_9am():
    ts = pd.Series(pd.date_range("2024-01-01 09:00", periods=1, freq="h"))
    # 2024-01-01 is Monday
    m = weekly_occupied_mask(ts, weekdays=[0, 1, 2, 3, 4], start_hour=8, end_hour=17)
    assert bool(m.iloc[0]) is True


def test_weekly_unoccupied_saturday():
    ts = pd.Series(pd.date_range("2024-01-06 10:00", periods=1, freq="h"))
    # 2024-01-06 is Saturday
    m = weekly_occupied_mask(ts, weekdays=[0, 1, 2, 3, 4], start_hour=8, end_hour=17)
    assert bool(m.iloc[0]) is False


def test_weekly_unoccupied_monday_7am():
    ts = pd.Series(pd.date_range("2024-01-01 07:30", periods=1, freq="min"))
    m = weekly_occupied_mask(ts, weekdays=[0, 1, 2, 3, 4], start_hour=8, end_hour=17)
    assert bool(m.iloc[0]) is False


def test_weather_band_fahrenheit():
    oat = pd.Series([31.0, 50.0, 86.0])
    m = weather_allows_fdd_mask(oat, low=32, high=85)
    assert list(m) == [False, True, False]


def test_datetime_series_from_column():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01 12:00", periods=3, freq="h"),
            "x": [1, 2, 3],
        }
    )
    s = datetime_series_for_rows(df, timestamp_col="timestamp")
    assert len(s) == 3


def test_datetime_series_from_index():
    idx = pd.date_range("2024-01-02 12:00", periods=2, freq="h")
    df = pd.DataFrame({"x": [1, 2]}, index=idx)
    s = datetime_series_for_rows(df, timestamp_col=None)
    assert s.iloc[0] == idx[0]


def test_expression_schedule_weather_fan_unoccupied():
    """Fan on during unoccupied hours, OAT in band → fault."""
    ts = pd.date_range("2024-01-06 10:00", periods=4, freq="h")  # Saturday
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "fan": [0.0, 0.9, 0.0, 0.95],
            "oat": [50.0, 50.0, 50.0, 50.0],
        }
    )
    rule_params = {
        "fan_on": 0.01,
        "schedule": {
            "weekdays": [0, 1, 2, 3, 4],
            "start_hour": 8,
            "end_hour": 17,
        },
        "weather_band": {
            "enabled": True,
            "oat_input": "Outside_Air_Temperature_Sensor",
            "low": 32,
            "high": 85,
            "units": "imperial",
        },
    }
    col_map = {
        "Supply_Fan_Speed_Command": "fan",
        "Outside_Air_Temperature_Sensor": "oat",
    }
    expr = (
        "(Supply_Fan_Speed_Command > fan_on) & ~schedule_occupied & weather_allows_fdd"
    )
    mask = check_expression(
        df, expr, col_map, rule_params, timestamp_col="timestamp"
    )
    assert mask.tolist() == [False, True, False, True]


def test_expression_weather_extreme_suppresses():
    """OAT above band → weather_allows_fdd False → no fault even if fan on unoccupied."""
    ts = pd.date_range("2024-01-06 10:00", periods=2, freq="h")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "fan": [0.95, 0.95],
            "oat": [50.0, 90.0],
        }
    )
    rule_params = {
        "fan_on": 0.01,
        "schedule": {
            "weekdays": [0, 1, 2, 3, 4],
            "start_hour": 8,
            "end_hour": 17,
        },
        "weather_band": {
            "oat_input": "Outside_Air_Temperature_Sensor",
            "low": 32,
            "high": 85,
            "units": "imperial",
        },
    }
    col_map = {
        "Supply_Fan_Speed_Command": "fan",
        "Outside_Air_Temperature_Sensor": "oat",
    }
    expr = (
        "(Supply_Fan_Speed_Command > fan_on) & ~schedule_occupied & weather_allows_fdd"
    )
    mask = check_expression(
        df, expr, col_map, rule_params, timestamp_col="timestamp"
    )
    assert mask.tolist() == [True, False]


def test_weather_band_metric():
    df = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-06 10:00")],
            "oat": [15.0],  # ~59F - in 0-29C band
        }
    )
    params = {
        "weather_band": {
            "oat_input": "Outside_Air_Temperature_Sensor",
            "low": 0.0,
            "high": 29.5,
            "units": "metric",
        },
    }
    col_map = {"Outside_Air_Temperature_Sensor": "oat"}
    mask = check_expression(
        df,
        "weather_allows_fdd",
        col_map,
        params,
        timestamp_col="timestamp",
    )
    assert bool(mask.iloc[0]) is True


def test_missing_oat_for_weather_raises():
    df = pd.DataFrame({"timestamp": [pd.Timestamp("2024-01-06 10:00")], "x": [1]})
    with pytest.raises(ValueError, match="weather_band requires"):
        check_expression(
            df,
            "weather_allows_fdd",
            {},
            {
                "weather_band": {
                    "oat_input": "Outside_Air_Temperature_Sensor",
                    "low": 0,
                    "high": 30,
                    "units": "metric",
                },
            },
            timestamp_col="timestamp",
        )


def test_rule_runner_end_to_end():
    from open_fdd.engine import RuleRunner

    ts = pd.date_range("2024-01-06 09:00", periods=3, freq="h")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "fan": [0.0, 0.9, 0.0],
            "oat": [55.0, 55.0, 55.0],
        }
    )
    rule = {
        "name": "operating_unoccupied",
        "type": "expression",
        "flag": "unocc_flag",
        "inputs": {
            "Supply_Fan_Speed_Command": {"column": "fan"},
            "Outside_Air_Temperature_Sensor": {"column": "oat"},
        },
        "params": {
            "fan_on": 0.01,
            "schedule": {
                "weekdays": [0, 1, 2, 3, 4],
                "start_hour": 8,
                "end_hour": 17,
            },
            "weather_band": {
                "oat_input": "Outside_Air_Temperature_Sensor",
                "low": 32,
                "high": 85,
                "units": "imperial",
            },
        },
        "expression": (
            "(Supply_Fan_Speed_Command > fan_on) & ~schedule_occupied & weather_allows_fdd"
        ),
    }
    out = RuleRunner(rules=[rule]).run(df, timestamp_col="timestamp")
    assert out["unocc_flag"].tolist() == [0, 1, 0]
