"""Default engineering units for cookbook roles / Haystack points (no mixed-unit plots)."""

from __future__ import annotations

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
