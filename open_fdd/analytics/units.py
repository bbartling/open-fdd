"""Default engineering units for cookbook roles / Haystack points (no mixed-unit plots)."""

from __future__ import annotations

from typing import Any

# Cookbook role → display unit
DEFAULT_ROLE_UNITS: dict[str, str] = {
    "discharge-air-temp": "°F",
    "discharge-air-temp-sp": "°F",
    "mixed-air-temp": "°F",
    "return-air-temp": "°F",
    "outside-air-temp": "°F",
    "vav-discharge-air-temp": "°F",
    "vav-inlet-air-temp": "°F",
    "ahu-discharge-air-temp": "°F",
    "chilled-water-supply-temp": "°F",
    "chilled-water-return-temp": "°F",
    "hot-water-supply-temp": "°F",
    "hot-water-return-temp": "°F",
    "zone-air-temp": "°F",
    "outside-air-damper": "%",
    "cooling-valve": "%",
    "heating-valve": "%",
    "damper": "%",
    "reheat-valve": "%",
    "fan-cmd": "%",
    "control-output-pct": "%",
    "loop-enabled": "",
    "fan-status": "bool",
    "pump-status": "bool",
    "chw-pump-status": "bool",
    "hw-pump-status": "bool",
    "compressor-status": "bool",
    "compressor-cmd": "bool",
    "compressor-stage-1": "bool",
    "compressor-stage-2": "bool",
    "compressor-power": "kW",
    "compressor-current": "A",
    "heat-pump-cooling-status": "bool",
    "unit-cooling-status": "bool",
    "vrf-outdoor-compressor-status": "bool",
    "chiller-status": "bool",
    "motor-on": "bool",
    "web-outside-air-temp": "°F",
    "web-outside-air-dewpoint": "°F",
    "web-outside-air-wetbulb": "°F",
    "web-outside-air-humidity": "%",
    "duct-static-pressure": "in. w.c.",
    "duct-static-pressure-sp": "in. w.c.",
    "zone-airflow": "cfm",
    "min-flow-sp": "cfm",
    "occupied": "bool",
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
    """Attach ``unit_system`` and ``units_map`` on ``frame.attrs``.

    A column map with ``unit_system`` or ``units`` wins over a map already
    stamped by the history source.
    """
    column_map = column_map or {}
    raw_overrides = column_map.get("units") if isinstance(column_map.get("units"), dict) else None
    has_map = bool(column_map.get("unit_system") or raw_overrides)
    if not has_map:
        existing = frame.attrs.get("units_map")
        if isinstance(existing, dict) and existing:
            frame.attrs["unit_system"] = str(frame.attrs.get("unit_system") or "imperial")
            return {str(k): str(v) for k, v in existing.items() if v}
    system = column_map.get("unit_system") or frame.attrs.get("unit_system") or "imperial"
    units = report_units_map(str(system), raw_overrides)
    frame.attrs["unit_system"] = str(system)
    frame.attrs["units_map"] = units
    return units
