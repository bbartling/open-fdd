"""BACnet unit conversion profiles."""

from __future__ import annotations

from openfdd_bridge.bacnet_value_convert import convert_poll_value, profile_for_sample


def test_metric_temp_to_fahrenheit():
    val, units = convert_poll_value(20.0, units="degrees-celsius", profile="metric_temp_f")
    assert abs(val - 68.0) < 0.01
    assert "fahrenheit" in units


def test_profile_for_sample_device_override():
    prof = profile_for_sample(
        point_id="12033-analog-input-1",
        device_instance="12033",
        device_profiles={"12033": "metric_temp_f"},
        point_profiles={},
    )
    assert prof == "metric_temp_f"


def test_profile_for_sample_point_override():
    prof = profile_for_sample(
        point_id="12033-analog-input-1",
        device_instance="12033",
        device_profiles={"12033": "metric_temp_f"},
        point_profiles={"12033-analog-input-1": "point_override"},
    )
    assert prof == "point_override"
