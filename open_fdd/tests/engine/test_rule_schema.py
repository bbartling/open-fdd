"""Pydantic coercion for rule params (schedule, weather_band, scalars)."""

import pytest

from open_fdd.engine.rule_schema import coerce_rule_params


def test_coerce_schedule_defaults():
    out = coerce_rule_params(
        {"schedule": {"weekdays": [0, 1, 2, 3, 4], "start_hour": 7, "end_hour": 18}}
    )
    assert out["schedule"]["start_hour"] == 7
    assert out["schedule"]["end_hour"] == 18


def test_coerce_schedule_rejects_bad_weekday_type():
    with pytest.raises(Exception):
        coerce_rule_params({"schedule": {"weekdays": "not-a-list"}})


def test_coerce_weather_band_units():
    out = coerce_rule_params(
        {
            "weather_band": {
                "low": 30,
                "high": 90,
                "units": "imperial",
            }
        }
    )
    assert out["weather_band"]["low"] == 30.0


def test_coerce_weather_band_rejects_bad_units():
    with pytest.raises(Exception):
        coerce_rule_params({"weather_band": {"units": "kelvin"}})


def test_coerce_string_numeric_params():
    out = coerce_rule_params({"sp_margin": "0.12", "drv_hi_frac": "93"})
    assert out["sp_margin"] == 0.12
    assert out["drv_hi_frac"] == 93


def test_coerce_ignores_unknown_nested_dict_keys_in_schedule():
    out = coerce_rule_params(
        {"schedule": {"start_hour": 9, "end_hour": 17, "comment": "office"}}
    )
    assert "comment" not in out["schedule"]
