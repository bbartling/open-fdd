"""Sensor catalog defaults for Arrow cookbook."""

from __future__ import annotations

import pyarrow as pa

from open_fdd.arrow_runtime.cookbook import mixing_envelope_mask, sensor_bounds_mask
from open_fdd.arrow_runtime.sensor_catalog import cfg_from_profile, profile


def test_zone_temp_profile_bounds():
    p = profile("zone_temp")
    assert p["bounds_low"] == 55.0
    assert p["bounds_high"] == 90.0
    assert "VAV-C" in p["fault_codes"]


def test_cfg_from_profile_overrides():
    cfg = cfg_from_profile("co2", {"bounds_high": 1200.0})
    assert cfg["bounds_high"] == 1200.0
    assert cfg["bounds_low"] == 400.0


def test_sensor_bounds_mask_flags_oob():
    table = pa.table({"zone_temp": [70.0, 95.0, 60.0]})
    mask = sensor_bounds_mask(table, "zone_temp")
    assert mask.to_pylist() == [False, True, False]


def test_mixing_envelope_mask():
    table = pa.table(
        {
            "mixed_air_temp": [55.0, 35.0],
            "outside_air_temp": [40.0, 40.0],
            "return_air_temp": [70.0, 70.0],
            "supply_fan_speed_command": [0.5, 0.5],
        }
    )
    mask = mixing_envelope_mask(table, {"mixing_tol": 1.0})
    assert mask.to_pylist()[0] is False  # MAT inside OAT–RAT band
    assert mask.to_pylist()[1] is True  # MAT below band
