"""W5c: web weather declared in °F is normalized to SI once at the storage boundary.

Economizer weather-summary thresholds and resolve_web_drybulb dewpoint SI fixes
live on W4f (#1447) — do not patch core.py::economizer_weather_summary here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.rules.economizer_weather import resolve_web_drybulb_dewpoint
from open_fdd.rules.runner import merge_weather
from open_fdd.units.convert import source_temperature_to_si


def test_web_oat_declared_fahrenheit_not_double_converted_at_merge():
    idx = pd.date_range("2026-06-01", periods=6, freq="5min", tz="UTC")
    si_oat = source_temperature_to_si(60.0, "°F")
    si_dp = source_temperature_to_si(45.0, "°F")

    equipment = pd.DataFrame(
        {
            "outside-air-damper": [0.55] * len(idx),
            "cooling-valve": [0.0] * len(idx),
            "fan-status": [1.0] * len(idx),
        },
        index=idx,
    )
    weather = pd.DataFrame(
        {
            "web-outside-air-temp": [si_oat] * len(idx),
            "web-outside-air-dewpoint": [si_dp] * len(idx),
        },
        index=idx,
    )
    merged = merge_weather(equipment, weather)
    db, dp, _src = resolve_web_drybulb_dewpoint(merged)
    assert db is not None and dp is not None
    assert float(db.iloc[0]) == pytest.approx(si_oat, abs=1e-9)
    assert float(dp.iloc[0]) == pytest.approx(si_dp, abs=1e-9)

    wrong_double = source_temperature_to_si(float(db.iloc[0]), "°F")
    assert wrong_double < si_oat - 1.0
