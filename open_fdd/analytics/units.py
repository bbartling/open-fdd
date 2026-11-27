"""Default engineering units for cookbook roles / Haystack points (no mixed-unit plots)."""

from __future__ import annotations

from typing import Any

# Cookbook role → display unit
DEFAULT_ROLE_UNITS: dict[str, str] = {
    "discharge_air_temperature": "°F",
    "discharge_air_temperature_setpoint": "°F",
    "mixed_air_temperature": "°F",
    "return_air_temperature": "°F",
    "outdoor_air_intake_temperature": "°F",
    "terminal_unit_discharge_air_temperature": "°F",
    "terminal_unit_inlet_air_temperature": "°F",
    "air_handling_unit_discharge_air_temperature": "°F",
    "supply_chilled_water_temperature": "°F",
    "return_chilled_water_temperature": "°F",
    "supply_hot_water_temperature": "°F",
    "return_hot_water_temperature": "°F",
    "zone_air_temperature": "°F",
    "outdoor_air_intake_damper_position_command": "%",
    "cooling_valve_position_command": "%",
    "heating_valve_position_command": "%",
    "damper_position": "%",
    "terminal_unit_heating_valve_position_command": "%",
    "supply_fan_command": "%",
    "control-output-pct": "%",
    "operating_mode_status": "",
    "supply_fan_operating_status": "bool",
    "pump_operating_status": "bool",
    "chilled_water_pump_operating_status": "bool",
    "hw-pump-status": "bool",
    "compressor_operating_status": "bool",
    "compressor-cmd": "bool",
    "compressor-stage-1": "bool",
    "compressor-stage-2": "bool",
    "compressor-power": "kW",
    "compressor-current": "A",
    "heat-pump-cooling-status": "bool",
    "unit-cooling-status": "bool",
    "vrf-outdoor-compressor-status": "bool",
    "chiller_operating_status": "bool",
    "motor-on": "bool",
    "weather_service_air_temperature": "°F",
    "weather_service_air_dew_point_temperature": "°F",
    "weather_service_air_wet_bulb_temperature": "°F",
    "weather_service_air_relative_humidity": "%",
    "outdoor_air_intake_relative_humidity": "%",
    "return_air_relative_humidity": "%",
    "zone_air_relative_humidity": "%",
    "zone-humidity": "%",
    "mixed_air_relative_humidity": "%",
    "discharge_air_relative_humidity": "%",
    "discharge_air_static_pressure": "in. w.c.",
    "discharge_air_static_pressure_setpoint": "in. w.c.",
    "discharge_air_volume_flow_rate": "cfm",
    "discharge_air_volume_flow_rate_minimum": "cfm",
    "occupancy_status": "bool",
}

# Unit family key used to group series onto the same subplot (never mix families).
UNIT_FAMILY: dict[str, str] = {
    "°F": "temp_F",
    "degF": "temp_F",
    "F": "temp_F",
    "°C": "temp_C",
    "degC": "temp_C",
    "C": "temp_C",
    "%": "pct",
    "percent": "pct",
    "in. w.c.": "static",
    "inWC": "static",
    "in_wc": "static",
    "Pa": "static_Pa",
    "cfm": "flow",
    "L/s": "flow_metric",
    "bool": "bool",
    "0/1": "bool",
}


def unit_family(unit: str) -> str:
    u = (unit or "").strip()
    return UNIT_FAMILY.get(u, UNIT_FAMILY.get(u.lower(), f"other:{u or 'unknown'}"))


def resolve_role_unit(role: str, units_map: dict[str, str] | None = None) -> str:
    if units_map and role in units_map and units_map[role]:
        return str(units_map[role])
    return DEFAULT_ROLE_UNITS.get(role, "")


def is_metric_unit_system(unit_system: str | None) -> bool:
    return str(unit_system or "").strip().lower() in {"metric", "si"}


def report_units_map(
    unit_system: str | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Display units for report axes and captions.

    Imperial (the default) is °F and in. w.c. ``metric`` / ``si`` is °C and Pa.
    ``overrides`` are per-role labels for the stored series and win over the
    system default. Values are plotted as stored; this map only names them.
    """
    metric = is_metric_unit_system(unit_system)
    out = dict(DEFAULT_ROLE_UNITS)
    if metric:
        for role, unit in list(out.items()):
            if unit == "°F":
                out[role] = "°C"
            elif unit == "in. w.c.":
                out[role] = "Pa"
    if overrides:
        for role, unit in overrides.items():
            if unit:
                out[str(role)] = str(unit)
    return out


def stamp_display_units(frame: Any, column_map: dict | None = None) -> dict[str, str]:
    """Attach ``display_units`` and ``units_map`` on ``frame.attrs``.

    A column map with ``display_units`` or ``units`` wins over a map already
    stamped by the history source.
    """
    column_map = column_map or {}
    raw_overrides = column_map.get("units") if isinstance(column_map.get("units"), dict) else None
    has_map = bool(column_map.get("display_units") or raw_overrides)
    if not has_map:
        existing = frame.attrs.get("units_map")
        if isinstance(existing, dict) and existing:
            frame.attrs["display_units"] = str(frame.attrs.get("display_units") or "imperial")
            return {str(k): str(v) for k, v in existing.items() if v}
    system = column_map.get("display_units") or frame.attrs.get("display_units") or "imperial"
    units = report_units_map(str(system), raw_overrides)
    frame.attrs["display_units"] = str(system)
    frame.attrs["units_map"] = units
    return units


def apply_unit_metadata(frame: Any, metadata: dict | None = None) -> dict[str, str]:
    from open_fdd.analytics.report_storage import apply_unit_metadata as _apply

    return _apply(frame, metadata)
