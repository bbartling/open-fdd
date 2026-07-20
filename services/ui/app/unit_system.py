"""Imperial ↔ metric display conversion for Streamlit charts / tables.

Internal rule math stays in imperial (°F, in.w.c., cfm) — convert only at the UI edge.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

UnitSystem = Literal["imperial", "metric"]

# role → (imperial_unit, metric_unit, convert_fn imperial→metric)
_TEMP_ROLES = {
    "discharge-air-temp", "discharge-air-temp-sp", "mixed-air-temp", "return-air-temp", "outside-air-temp", "web-outside-air-temp", "web-outside-air-dewpoint", "web-outside-air-wetbulb",
    "vav-discharge-air-temp", "vav-inlet-air-temp", "chilled-water-supply-temp", "chilled-water-return-temp", "hot-water-supply-temp", "hot-water-return-temp",
    "zone-air-temp", "condenser-water-supply-temp", "condenser-water-return-temp", "cw_return_t",
}
_STATIC_ROLES = {"duct-static-pressure", "duct-static-pressure-sp"}
_FLOW_ROLES = {"zone-airflow", "min-flow-sp"}


def f_to_c(v: float) -> float:
    return (float(v) - 32.0) * 5.0 / 9.0


def c_to_f(v: float) -> float:
    return float(v) * 9.0 / 5.0 + 32.0


def inwc_to_pa(v: float) -> float:
    return float(v) * 249.0889


def cfm_to_ls(v: float) -> float:
    return float(v) * 0.47194745


def convert_series(role: str, series: pd.Series, system: UnitSystem) -> tuple[pd.Series, str]:
    """Return (converted series, display unit) for a cookbook role."""
    s = pd.to_numeric(series, errors="coerce")
    if system == "imperial":
        from app.units import DEFAULT_ROLE_UNITS

        return s, DEFAULT_ROLE_UNITS.get(role, "")
    if role in _TEMP_ROLES or role.endswith("_t") or "temp" in role.lower() or "dewpoint" in role or "wetbulb" in role:
        return (s - 32.0) * 5.0 / 9.0, "°C"
    if role in _STATIC_ROLES or "static" in role.lower():
        return s * 249.0889, "Pa"
    if role in _FLOW_ROLES or "flow" in role.lower() and "gpm" not in role.lower():
        return s * 0.47194745, "L/s"
    from app.units import DEFAULT_ROLE_UNITS

    return s, DEFAULT_ROLE_UNITS.get(role, "")


def convert_scalar_threshold(role_or_unit: str, value: float, system: UnitSystem) -> float:
    """Convert a numeric threshold for display (imperial stored → metric display)."""
    if system == "imperial":
        return float(value)
    u = role_or_unit.lower()
    if u in {"°f", "degf", "f"} or role_or_unit in _TEMP_ROLES:
        return f_to_c(value)
    if "w.c" in u or role_or_unit in _STATIC_ROLES:
        return inwc_to_pa(value)
    if u == "cfm" or role_or_unit in _FLOW_ROLES:
        return cfm_to_ls(value)
    return float(value)


def display_unit_for_role(role: str, system: UnitSystem) -> str:
    from app.units import DEFAULT_ROLE_UNITS

    if system == "imperial":
        return DEFAULT_ROLE_UNITS.get(role, "")
    if role in _TEMP_ROLES:
        return "°C"
    if role in _STATIC_ROLES:
        return "Pa"
    if role in _FLOW_ROLES:
        return "L/s"
    return DEFAULT_ROLE_UNITS.get(role, "")


def units_map_for_system(base: dict[str, str] | None, system: UnitSystem) -> dict[str, str]:
    """Rewrite a units map for the active display system."""
    from app.units import DEFAULT_ROLE_UNITS

    src = dict(DEFAULT_ROLE_UNITS)
    if base:
        src.update(base)
    if system == "imperial":
        return src
    out: dict[str, str] = {}
    for role, unit in src.items():
        out[role] = display_unit_for_role(role, "metric") or unit
    return out
