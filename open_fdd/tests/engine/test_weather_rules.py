"""Tests for weather fault rules."""

import pandas as pd
import pytest

from open_fdd.engine import RuleRunner
from pathlib import Path


@pytest.fixture
def weather_df():
    """Sample weather DataFrame (hourly)."""
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-15", periods=24, freq="h"),
        "temp_f": [45.0, 44.5, 44.0, 44.0, 44.0, 44.0, 44.0, 44.5, 50.0, 55.0]
        + [60.0] * 14,
        "rh_pct": [78, 80, 82, 83, 84, 85, 86, 84, 75, 65] + [50] * 14,
        "wind_mph": [12.0, 11.5, 10.0, 9.5, 9.0, 8.5, 8.0, 9.0, 12.0, 15.0]
        + [10.0] * 14,
        "gust_mph": [15.0, 14.2, 13.0, 12.5, 11.0, 10.5, 10.0, 11.0, 18.0, 22.0]
        + [15.0] * 14,
    })


def test_weather_rules_load(weather_df):
    """Weather rules load and run from rules dir."""
    rules_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    runner = RuleRunner(rules_path=rules_dir)
    weather_rules = [r for r in runner._rules if r.get("name", "").startswith("weather_")]
    assert len(weather_rules) >= 4

    result = runner.run(
        weather_df,
        timestamp_col="ts",
        params={"rh_min": 0, "rh_max": 100, "temp_spike_f_per_hour": 15, "tolerance": 0.2, "window": 6},
        skip_missing_columns=True,
    )
    assert "fault_rh_out_of_range" in result.columns
    assert "fault_temp_spike" in result.columns
    assert "fault_temp_stuck" in result.columns
    assert "fault_gust_lt_wind" in result.columns


def test_weather_rh_out_of_range(weather_df):
    """RH out of range flags invalid values."""
    rules_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    runner = RuleRunner(rules_path=rules_dir)
    runner._rules = [r for r in runner._rules if r.get("name") == "weather_rh_out_of_range"]

    result = runner.run(weather_df, params={"rh_min": 0, "rh_max": 100})
    # All rh in 50-86, within [0,100]
    assert result["fault_rh_out_of_range"].sum() == 0

    result2 = runner.run(weather_df, params={"rh_min": 70, "rh_max": 85})
    # Some rh < 70 or > 85
    assert result2["fault_rh_out_of_range"].sum() > 0


def test_weather_gust_lt_wind(weather_df):
    """Gust < wind flags sensor error."""
    # Inject fault: gust < wind
    df = weather_df.copy()
    df.loc[5, "gust_mph"] = 7.0  # wind is 8.5
    df.loc[6, "gust_mph"] = 6.0  # wind is 8.0

    rules_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    runner = RuleRunner(rules_path=rules_dir)
    runner._rules = [r for r in runner._rules if r.get("name") == "weather_gust_lt_wind"]

    result = runner.run(df)
    assert result["fault_gust_lt_wind"].sum() >= 2
