"""Default sensor bounds, flatline, and rate-of-change profiles (Arrow Rule Lab).

Imperial (°F, inH2O, ppm) defaults match the expression cookbook and fault-code
catalog. Override per site via rule ``cfg`` or module constants in ``rules_py``.
"""

from __future__ import annotations

from typing import Any

# kind → profile dict (bounds, flatline, rate limits at 5-min poll unless noted)
SENSOR_PROFILES: dict[str, dict[str, Any]] = {
    "zone_temp": {
        "label": "Zone air temperature",
        "value_kind": "temp",
        "bounds_low": 55.0,
        "bounds_high": 90.0,
        "flatline_tolerance": 0.10,
        "window_samples": 12,
        "max_per_hour": 4.0,
        "max_per_15min": 2.0,
        "max_spread_24h": 10.0,
        "fault_codes": ["VAV-C"],
        "brick": "Zone_Air_Temperature_Sensor",
    },
    "supply_air_temp": {
        "label": "Supply air temperature",
        "value_kind": "temp",
        "bounds_low": 50.0,
        "bounds_high": 110.0,
        "flatline_tolerance": 0.15,
        "window_samples": 12,
        "max_per_hour": 8.0,
        "max_per_15min": 3.0,
        "max_spread_24h": 15.0,
        "fault_codes": ["AHU-C", "RTU-C"],
        "brick": "Supply_Air_Temperature_Sensor",
    },
    "return_air_temp": {
        "label": "Return air temperature",
        "value_kind": "temp",
        "bounds_low": 55.0,
        "bounds_high": 95.0,
        "flatline_tolerance": 0.10,
        "window_samples": 12,
        "max_per_hour": 3.0,
        "max_per_15min": 1.5,
        "max_spread_24h": 8.0,
        "fault_codes": ["AHU-D"],
        "brick": "Return_Air_Temperature_Sensor",
        "note": "Narrow band vs zone/OAT — use mixing_envelope when MAT/OAT/RAT available.",
    },
    "mixed_air_temp": {
        "label": "Mixed air temperature",
        "value_kind": "temp",
        "bounds_low": 40.0,
        "bounds_high": 110.0,
        "flatline_tolerance": 0.15,
        "window_samples": 12,
        "max_per_hour": 6.0,
        "max_per_15min": 2.5,
        "fault_codes": ["AHU-D"],
        "brick": "Mixed_Air_Temperature_Sensor",
    },
    "outdoor_air_temp": {
        "label": "Outdoor air temperature",
        "value_kind": "temp",
        "bounds_low": -40.0,
        "bounds_high": 130.0,
        "flatline_tolerance": 0.10,
        "window_samples": 12,
        "max_per_hour": 12.0,
        "max_per_15min": 6.0,
        "max_spread_24h": 25.0,
        "fault_codes": ["BLD-B"],
        "brick": "Outside_Air_Temperature_Sensor",
    },
    "duct_static_pressure": {
        "label": "Duct static pressure",
        "value_kind": "pressure_inh2o",
        "bounds_low": -0.5,
        "bounds_high": 3.0,
        "flatline_tolerance": 0.02,
        "window_samples": 12,
        "max_per_hour": 0.5,
        "max_per_15min": 0.25,
        "fault_codes": ["AHU-A"],
        "brick": "Supply_Air_Static_Pressure_Sensor",
    },
    "relative_humidity": {
        "label": "Relative humidity",
        "value_kind": "rh",
        "bounds_low_rh": 0.0,
        "bounds_high_rh": 100.0,
        "flatline_tolerance_rh": 1.0,
        "window_samples": 12,
        "max_per_hour": 15.0,
        "max_per_15min": 8.0,
        "fault_codes": ["DC-C"],
        "brick": "Relative_Humidity_Sensor",
    },
    "chilled_water_temp": {
        "label": "Chilled water temperature",
        "value_kind": "temp",
        "bounds_low": 40.0,
        "bounds_high": 90.0,
        "flatline_tolerance": 0.10,
        "window_samples": 12,
        "max_per_hour": 4.0,
        "max_per_15min": 2.0,
        "fault_codes": ["CH-D"],
        "brick": "Chilled_Water_Supply_Temperature_Sensor",
    },
    "hot_water_temp": {
        "label": "Hot water temperature",
        "value_kind": "temp",
        "bounds_low": 70.0,
        "bounds_high": 200.0,
        "flatline_tolerance": 0.15,
        "window_samples": 12,
        "max_per_hour": 6.0,
        "max_per_15min": 3.0,
        "fault_codes": ["CH-D"],
        "brick": "Hot_Water_Supply_Temperature_Sensor",
    },
    "condenser_water_temp": {
        "label": "Condenser water temperature",
        "value_kind": "temp",
        "bounds_low": 50.0,
        "bounds_high": 110.0,
        "flatline_tolerance": 0.15,
        "window_samples": 12,
        "max_per_hour": 5.0,
        "max_per_15min": 2.5,
        "fault_codes": ["CH-A"],
        "brick": "Condenser_Water_Supply_Temperature_Sensor",
    },
    "co2": {
        "label": "CO₂ concentration",
        "value_kind": "co2",
        "bounds_low": 400.0,
        "bounds_high": 1000.0,
        "flatline_tolerance": 5.0,
        "window_samples": 12,
        "max_per_hour": 200.0,
        "max_per_15min": 80.0,
        "fault_codes": ["VAV-B"],
        "brick": "CO2_Sensor",
        "note": "Upper bound is occupied ventilation target; raise for unoccupied rules.",
    },
    "discharge_air_temp": {
        "label": "Discharge / leaving air temperature",
        "value_kind": "temp",
        "bounds_low": 45.0,
        "bounds_high": 120.0,
        "flatline_tolerance": 0.15,
        "window_samples": 12,
        "max_per_hour": 10.0,
        "max_per_15min": 4.0,
        "fault_codes": ["VAV-E", "HP-D"],
        "brick": "Discharge_Air_Temperature_Sensor",
    },
}


def profile(kind: str) -> dict[str, Any]:
    key = str(kind or "").strip().lower()
    if key not in SENSOR_PROFILES:
        raise KeyError(f"unknown sensor kind '{kind}' — see SENSOR_PROFILES keys")
    return dict(SENSOR_PROFILES[key])


def cfg_from_profile(kind: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge catalog defaults with site overrides for Rule Lab ``cfg``."""
    base = profile(kind)
    base.pop("label", None)
    base.pop("fault_codes", None)
    base.pop("brick", None)
    base.pop("note", None)
    if overrides:
        base.update({k: v for k, v in overrides.items() if v is not None})
    return base
