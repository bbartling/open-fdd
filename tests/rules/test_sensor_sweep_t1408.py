"""T1408-1 sensor sweep coverage (humidity roles, flatline exclusions)."""

import numpy as np
import pandas as pd

from open_fdd.analytics.units import stamp_display_units
from open_fdd.rules.cookbook_catalog import FLATLINE_SENSOR_ROLES, _sweep_flatline, _sweep_range
from open_fdd.rules.sensor_sweep_catalog import is_expected_constant_role, sweep_assessable_role


def test_return_air_humidity_in_sweep_catalog():
    assert "return-air-humidity" in FLATLINE_SENSOR_ROLES


def test_ra_h_range_and_flatline_with_declared_unit():
    frame = pd.DataFrame({"return-air-humidity": [45.0] * 269})
    stamp_display_units(frame)
    range_mask = _sweep_range(frame, {}, 300.0)
    assert not range_mask.any()
    flat_mask = _sweep_flatline(frame, {"flatline_hours": 1.0, "flatline_tol": 0.1}, 300.0)
    assert flat_mask.sum() >= 1


def test_constant_setpoint_not_assessed_for_flatline():
    frame = pd.DataFrame({"discharge-air-temp-sp": [55.0] * 50})
    stamp_display_units(frame)
    assert is_expected_constant_role("discharge-air-temp-sp")
    assert not sweep_assessable_role("discharge-air-temp-sp", None, frame.attrs.get("units_map"))
    flat_mask = _sweep_flatline(frame, {"flatline_hours": 1.0}, 300.0)
    assert not flat_mask.any()


def test_humidity_without_unit_not_assessed():
    frame = pd.DataFrame({"return-air-humidity": [40.0] * 20})
    frame.attrs["units_map"] = {}
    assert not sweep_assessable_role("return-air-humidity", None, {})
    flat_mask = _sweep_flatline(frame, {"flatline_hours": 1.0}, 300.0)
    assert not flat_mask.any()


def test_sv_range_flags_out_of_range_humidity():
    frame = pd.DataFrame({"return-air-humidity": [120.0]})
    stamp_display_units(frame)
    mask = _sweep_range(frame, {}, 300.0)
    assert mask.iloc[0]
