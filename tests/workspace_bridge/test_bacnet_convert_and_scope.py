"""BACnet unit conversion profiles."""

from __future__ import annotations

from pathlib import Path

from openfdd_bridge.bacnet_value_convert import _load_device_profiles, convert_poll_value, profile_for_sample


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


def test_load_device_profiles_range_csv(tmp_path: Path):
    path = tmp_path / "device_poll_profiles.csv"
    path.write_text(
        "device_instance,convert_profile,notes\n11000-13000,metric_temp_f,Trane range\n42,none,JCI\n",
        encoding="utf-8",
    )
    exact, ranges = _load_device_profiles(path)
    assert exact == {"42": "none"}
    assert ranges == [(11000, 13000, "metric_temp_f")]


def test_device_instance_range_profile():
    exact, ranges = {}, [(11000, 13000, "metric_temp_f")]
    prof = profile_for_sample(
        point_id="12099-analog-input-1",
        device_instance="12099",
        device_profiles=exact,
        point_profiles={},
        device_profile_ranges=ranges,
    )
    assert prof == "metric_temp_f"
    prof_jci = profile_for_sample(
        point_id="25-analog-input-1",
        device_instance="25",
        device_profiles=exact,
        point_profiles={},
        device_profile_ranges=ranges,
    )
    assert prof_jci == ""


def test_profile_for_sample_point_override():
    prof = profile_for_sample(
        point_id="12033-analog-input-1",
        device_instance="12033",
        device_profiles={"12033": "metric_temp_f"},
        point_profiles={"12033-analog-input-1": "point_override"},
    )
    assert prof == "point_override"
