"""SV-RATE sensor rate-of-change profiles (engineering screening defaults).

Thresholds are configurable screening values — not universal code limits.
All thresholds are SI (delta-degC/h, Pa/h); display conversion is separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

Quantity = Literal[
    "temperature",
    "relative_humidity",
    "co2",
    "air_pressure",
    "hydronic_pressure",
    "flow",
    "command_position",
]


@dataclass(frozen=True)
class SensorRateProfile:
    profile_id: str
    quantity: Quantity
    location: str
    canonical_unit: str
    steady_warning_per_hour: float
    steady_fault_per_hour: float
    transient_warning_per_hour: float
    transient_fault_per_hour: float
    persistence_minutes: int = 10
    transition_window_minutes: int = 15
    extreme_interval_change: float | None = None
    extreme_interval_minutes: int | None = 5
    normalize_by: str | None = None  # "design_flow" | "sensor_span" | None
    noise_deadband: float = 0.0
    rationale: str = ""

    def validate(self) -> None:
        if self.steady_warning_per_hour < 0 or self.steady_fault_per_hour < 0:
            raise ValueError(f"{self.profile_id}: thresholds must be nonnegative")
        if self.transient_warning_per_hour < 0 or self.transient_fault_per_hour < 0:
            raise ValueError(f"{self.profile_id}: thresholds must be nonnegative")
        if self.steady_fault_per_hour < self.steady_warning_per_hour:
            raise ValueError(f"{self.profile_id}: steady fault < warning")
        if self.transient_fault_per_hour < self.transient_warning_per_hour:
            raise ValueError(f"{self.profile_id}: transient fault < warning")
        if self.transient_warning_per_hour < self.steady_warning_per_hour:
            raise ValueError(f"{self.profile_id}: transient warning < steady warning")
        if self.transient_fault_per_hour < self.steady_fault_per_hour:
            raise ValueError(f"{self.profile_id}: transient fault < steady fault")
        if self.persistence_minutes <= 0:
            raise ValueError(f"{self.profile_id}: persistence must be > 0")
        if not self.canonical_unit:
            raise ValueError(f"{self.profile_id}: canonical_unit required")


def _t(
    pid: str,
    location: str,
    sw: float,
    sf: float,
    tw: float,
    tf: float,
    *,
    persist: int = 10,
    window: int = 15,
    extreme: float | None = None,
    rationale: str = "",
) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="temperature",
        location=location,
        canonical_unit="Δ°C/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=persist,
        transition_window_minutes=window,
        extreme_interval_change=extreme,
        extreme_interval_minutes=5,
        rationale=rationale or "Temperature rate screening default (Δ°C/h).",
    )


def _rh(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="relative_humidity",
        location=location,
        canonical_unit="pp/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=15,
        transition_window_minutes=15,
        extreme_interval_change=40.0,
        rationale="Relative humidity percentage-points per hour.",
    )


def _co2(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="co2",
        location=location,
        canonical_unit="ppm/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=15,
        transition_window_minutes=20,
        extreme_interval_change=3000.0,
        noise_deadband=100.0,
        rationale="CO2 ppm per hour; 100 ppm noise deadband.",
    )


def _air_p(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="air_pressure",
        location=location,
        canonical_unit="Pa/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=10,
        transition_window_minutes=20,
        rationale="Air pressure rate, Pa/h.",
    )


def _hyd_p(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="hydronic_pressure",
        location=location,
        canonical_unit="Pa/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=10,
        transition_window_minutes=10,
        normalize_by=None,
        rationale="Hydronic pressure rate, Pa/h.",
    )


def _flow(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="flow",
        location=location,
        canonical_unit="design-flow/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=10,
        transition_window_minutes=15,
        normalize_by="design_flow",
        rationale="Normalized by design flow or sensor span (fraction of full scale per hour).",
    )


def _cmd(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="command_position",
        location=location,
        canonical_unit="%/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=10,
        transition_window_minutes=10,
        rationale="Command/position rate; PID hunting remains a separate rule.",
    )


DEFAULT_PROFILES: dict[str, SensorRateProfile] = {
    # Temperature (delta-degC / h)
    "zone_air_temperature": _t("zone_air_temperature", "zone", 2.2222, 3.3333, 4.4444, 6.6667, extreme=8.3333, window=30),
    "return_air_temperature": _t("return_air_temperature", "return", 3.3333, 5.5556, 6.6667, 11.1111),
    "outside_air_temperature": _t("outside_air_temperature", "outside", 6.6667, 10.0, 11.1111, 16.6667, window=15),
    "mixed_air_temperature": _t("mixed_air_temperature", "mixed", 6.6667, 11.1111, 16.6667, 25.0, window=15),
    "supply_air_temperature": _t("supply_air_temperature", "supply", 5.5556, 8.8889, 19.4444, 27.7778, window=20),
    "heating_coil_leaving_air_temperature": _t(
        "heating_coil_leaving_air_temperature", "heating_coil_leave", 8.3333, 13.8889, 27.7778, 41.6667, window=10
    ),
    "cooling_coil_leaving_air_temperature": _t(
        "cooling_coil_leaving_air_temperature", "cooling_coil_leave", 6.6667, 11.1111, 19.4444, 27.7778, window=10
    ),
    "vav_discharge_air_temperature": _t(
        "vav_discharge_air_temperature", "vav_discharge", 6.6667, 11.1111, 19.4444, 27.7778
    ),
    "chilled_water_supply_temperature": _t(
        "chilled_water_supply_temperature", "chw_supply", 3.3333, 5.5556, 8.3333, 13.8889, window=30
    ),
    "chilled_water_return_temperature": _t(
        "chilled_water_return_temperature", "chw_return", 4.4444, 6.6667, 8.3333, 13.8889, window=30
    ),
    "hot_water_supply_temperature": _t(
        "hot_water_supply_temperature", "hw_supply", 8.3333, 13.8889, 27.7778, 41.6667, window=30
    ),
    "hot_water_return_temperature": _t(
        "hot_water_return_temperature", "hw_return", 6.6667, 11.1111, 16.6667, 27.7778, window=30
    ),
    "condenser_water_temperature": _t(
        "condenser_water_temperature", "cw", 5.5556, 8.8889, 11.1111, 16.6667, window=20
    ),
    "refrigerant_temperature": _t(
        "refrigerant_temperature", "refrigerant", 22.2222, 41.6667, 83.3333, 138.8889, window=15
    ),
    # RH (pp/h)
    "zone_relative_humidity": _rh("zone_relative_humidity", "zone", 10, 15, 15, 25),
    "return_air_relative_humidity": _rh("return_air_relative_humidity", "return", 12, 20, 20, 30),
    "outside_air_relative_humidity": _rh("outside_air_relative_humidity", "outside", 25, 35, 40, 60),
    "mixed_air_relative_humidity": _rh("mixed_air_relative_humidity", "mixed", 20, 30, 35, 50),
    "supply_air_relative_humidity": _rh("supply_air_relative_humidity", "supply", 20, 30, 45, 65),
    "humidifier_leaving_relative_humidity": _rh(
        "humidifier_leaving_relative_humidity", "humidifier", 25, 40, 60, 90
    ),
    # CO2
    "zone_co2": _co2("zone_co2", "zone", 500, 1200, 1200, 2500),
    "dense_occupancy_zone_co2": _co2("dense_occupancy_zone_co2", "zone_dense", 1000, 2000, 2000, 3500),
    "return_air_co2": _co2("return_air_co2", "return", 500, 1000, 1000, 2000),
    "outside_air_co2": _co2("outside_air_co2", "outside", 150, 300, 300, 500),
    # Air pressure (Pa / h)
    "building_static_pressure": _air_p("building_static_pressure", "building", 24.88, 49.77, 74.65, 124.42),
    "duct_static_pressure": _air_p("duct_static_pressure", "duct", 186.63, 311.05, 746.52, 1244.2),
    "filter_differential_pressure": _air_p("filter_differential_pressure", "filter", 62.21, 124.42, 248.84, 497.68),
    "vav_differential_pressure": _air_p("vav_differential_pressure", "vav_dp", 124.42, 248.84, 497.68, 995.36),
    # Hydronic (Pa / h)
    "hydronic_differential_pressure": _hyd_p("hydronic_differential_pressure", "hydronic_dp", 34473.8, 68947.6, 137895.1, 241316.5),
    "pump_pressure": _hyd_p("pump_pressure", "pump", 68947.6, 137895.1, 275790.3, 413685.4),
    "static_hydronic_pressure": _hyd_p("static_hydronic_pressure", "hydronic_static", 20684.3, 41368.5, 68947.6, 137895.1),
    # Flow (design-flow fraction / h)
    "vav_airflow": _flow("vav_airflow", "vav", 1.0, 2.0, 4.0, 6.0),
    "ahu_airflow": _flow("ahu_airflow", "ahu", 0.75, 1.5, 3.0, 5.0),
    "water_flow": _flow("water_flow", "water", 0.75, 1.5, 3.0, 5.0),
    # Commands
    "valve_position": _cmd("valve_position", "valve", 100, 250, 600, 1200),
    "damper_position": _cmd("damper_position", "damper", 150, 300, 1200, 2400),
    "vfd_speed": _cmd("vfd_speed", "vfd", 100, 250, 600, 1200),
}

# Validate uniqueness + invariants at import
_seen: set[str] = set()
for _pid, _prof in DEFAULT_PROFILES.items():
    if _pid in _seen:
        raise RuntimeError(f"duplicate profile id {_pid}")
    _seen.add(_pid)
    if _pid != _prof.profile_id:
        raise RuntimeError(f"profile key/id mismatch {_pid}")
    _prof.validate()


# Haystack / cookbook role → default profile
ROLE_TO_PROFILE: dict[str, str] = {
    "zone-air-temp": "zone_air_temperature",
    "return-air-temp": "return_air_temperature",
    "outside-air-temp": "outside_air_temperature",
    "mixed-air-temp": "mixed_air_temperature",
    "discharge-air-temp": "supply_air_temperature",
    "heating-coil-leaving-temp": "heating_coil_leaving_air_temperature",
    "cooling-coil-leaving-temp": "cooling_coil_leaving_air_temperature",
    "vav-discharge-air-temp": "vav_discharge_air_temperature",
    "chilled-water-supply-temp": "chilled_water_supply_temperature",
    "chilled-water-return-temp": "chilled_water_return_temperature",
    "hot-water-supply-temp": "hot_water_supply_temperature",
    "hot-water-return-temp": "hot_water_return_temperature",
    "condenser-water-supply-temp": "condenser_water_temperature",
    "duct-static-pressure": "duct_static_pressure",
    "chw-diff-pressure": "hydronic_differential_pressure",
    "zone-airflow": "vav_airflow",
    "vav-total-airflow": "ahu_airflow",
    "cooling-valve": "valve_position",
    "heating-valve": "valve_position",
    "reheat-valve": "valve_position",
    "outside-air-damper": "damper_position",
    "damper": "damper_position",
    "fan-cmd": "vfd_speed",
    "return-fan-cmd": "vfd_speed",
    "chw-pump-cmd": "vfd_speed",
    "hw-pump-cmd": "vfd_speed",
    "tower-fan-cmd": "vfd_speed",
    "zone-co2": "zone_co2",
    "return-air-co2": "return_air_co2",
    "outside-air-co2": "outside_air_co2",
    "zone-air-humidity": "zone_relative_humidity",
    "return-air-humidity": "return_air_relative_humidity",
    "outside-air-humidity": "outside_air_relative_humidity",
    "mixed-air-humidity": "mixed_air_relative_humidity",
    "supply-air-humidity": "supply_air_relative_humidity",
}

# Aliases (normalized lowercase) → profile
NAME_ALIASES: dict[str, str] = {
    "zt": "zone_air_temperature",
    "zone_t": "zone_air_temperature",
    "zone_temp": "zone_air_temperature",
    "rat": "return_air_temperature",
    "return_air_temp": "return_air_temperature",
    "oat": "outside_air_temperature",
    "outside_air_temp": "outside_air_temperature",
    "mat": "mixed_air_temperature",
    "mixed_air_temp": "mixed_air_temperature",
    "sat": "supply_air_temperature",
    "dat": "supply_air_temperature",
    "supply_air_temp": "supply_air_temperature",
    "lat": "cooling_coil_leaving_air_temperature",
    "duct_static": "duct_static_pressure",
    "building_pressure": "building_static_pressure",
    "zone_rh": "zone_relative_humidity",
    "return_rh": "return_air_relative_humidity",
    "outside_rh": "outside_air_relative_humidity",
    "zone_co2": "zone_co2",
    "return_co2": "return_air_co2",
    "outside_co2": "outside_air_co2",
    "chwst": "chilled_water_supply_temperature",
    "chwrt": "chilled_water_return_temperature",
    "hwst": "hot_water_supply_temperature",
    "hwrt": "hot_water_return_temperature",
}


TRANSITION_WINDOWS_MIN: dict[str, int] = {
    "fan_start_stop": 20,
    "compressor_stage": 15,
    "valve_transition": 10,
    "boiler_enable": 30,
    "chiller_enable": 30,
    "pump_transition": 10,
    "economizer_mode": 15,
    "occupancy": 30,
    "humidifier": 20,
}


def resolve_profile(
    *,
    role: str | None = None,
    point_name: str | None = None,
    override_id: str | None = None,
    equipment_type: str = "",
) -> tuple[SensorRateProfile | None, str]:
    """Return (profile, resolution_source)."""
    if override_id and override_id in DEFAULT_PROFILES:
        return DEFAULT_PROFILES[override_id], "user_override"
    if role and role in ROLE_TO_PROFILE:
        return DEFAULT_PROFILES[ROLE_TO_PROFILE[role]], "canonical_role"
    for raw in (point_name, role):
        if not raw:
            continue
        key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
        if key in NAME_ALIASES:
            return DEFAULT_PROFILES[NAME_ALIASES[key]], "name_alias"
        if key in DEFAULT_PROFILES:
            return DEFAULT_PROFILES[key], "profile_id"
    # Equipment-aware soft fallbacks
    et = (equipment_type or "").upper()
    if et == "VAV" and role in {"zone-air-temp", None}:
        return DEFAULT_PROFILES["zone_air_temperature"], "equipment_fallback"
    return None, "unresolved"


def profiles_by_quantity() -> dict[str, list[SensorRateProfile]]:
    out: dict[str, list[SensorRateProfile]] = {}
    for p in DEFAULT_PROFILES.values():
        out.setdefault(p.quantity, []).append(p)
    return out


def apply_profile_overrides(
    base: SensorRateProfile,
    overrides: dict[str, float] | None,
) -> SensorRateProfile:
    """Apply numeric threshold overrides from session params."""
    if not overrides:
        return base
    kwargs = {}
    for key in (
        "steady_warning_per_hour",
        "steady_fault_per_hour",
        "transient_warning_per_hour",
        "transient_fault_per_hour",
        "persistence_minutes",
        "transition_window_minutes",
        "noise_deadband",
    ):
        if key in overrides and overrides[key] is not None:
            kwargs[key] = type(getattr(base, key))(overrides[key])
    if not kwargs:
        return base
    out = replace(base, **kwargs)
    out.validate()
    return out


def _validate_default_profiles() -> None:
    seen: set[str] = set()
    for pid, prof in DEFAULT_PROFILES.items():
        if pid in seen or pid != prof.profile_id:
            raise ValueError(f"Profile id mismatch or duplicate: {pid}")
        seen.add(pid)
        prof.validate()


_validate_default_profiles()
