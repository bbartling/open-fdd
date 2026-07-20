"""SV-RATE sensor rate-of-change profiles (engineering screening defaults).

Thresholds are configurable screening values — not universal code limits.
Canonical units are used for computation; display conversion is separate.
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


IN_WC_TO_PA = 249.08891
PSI_TO_KPA = 6.894757
F_TO_C_RATE = 5.0 / 9.0


def f_per_h_to_c_per_h(rate_f: float) -> float:
    """Temperature *rate* conversion — no 32° offset."""
    return float(rate_f) * F_TO_C_RATE


def c_per_h_to_f_per_h(rate_c: float) -> float:
    return float(rate_c) / F_TO_C_RATE


def inwc_per_h_to_pa_per_h(rate: float) -> float:
    return float(rate) * IN_WC_TO_PA


def pa_per_h_to_inwc_per_h(rate: float) -> float:
    return float(rate) / IN_WC_TO_PA


def psi_per_h_to_kpa_per_h(rate: float) -> float:
    return float(rate) * PSI_TO_KPA


def kpa_per_h_to_psi_per_h(rate: float) -> float:
    return float(rate) / PSI_TO_KPA


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
        canonical_unit="°F/h",
        steady_warning_per_hour=sw,
        steady_fault_per_hour=sf,
        transient_warning_per_hour=tw,
        transient_fault_per_hour=tf,
        persistence_minutes=persist,
        transition_window_minutes=window,
        extreme_interval_change=extreme,
        extreme_interval_minutes=5,
        rationale=rationale or "Temperature rate screening default (°F/h).",
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
    # Store canonical Pa/h derived from in.w.c./h defaults
    return SensorRateProfile(
        profile_id=pid,
        quantity="air_pressure",
        location=location,
        canonical_unit="Pa/h",
        steady_warning_per_hour=inwc_per_h_to_pa_per_h(sw),
        steady_fault_per_hour=inwc_per_h_to_pa_per_h(sf),
        transient_warning_per_hour=inwc_per_h_to_pa_per_h(tw),
        transient_fault_per_hour=inwc_per_h_to_pa_per_h(tf),
        persistence_minutes=10,
        transition_window_minutes=20,
        rationale=f"Air pressure; authored as {sw}/{sf}/{tw}/{tf} in.w.c./h → Pa/h.",
    )


def _hyd_p(pid: str, location: str, sw: float, sf: float, tw: float, tf: float) -> SensorRateProfile:
    return SensorRateProfile(
        profile_id=pid,
        quantity="hydronic_pressure",
        location=location,
        canonical_unit="kPa/h",
        steady_warning_per_hour=psi_per_h_to_kpa_per_h(sw),
        steady_fault_per_hour=psi_per_h_to_kpa_per_h(sf),
        transient_warning_per_hour=psi_per_h_to_kpa_per_h(tw),
        transient_fault_per_hour=psi_per_h_to_kpa_per_h(tf),
        persistence_minutes=10,
        transition_window_minutes=10,
        normalize_by=None,
        rationale=f"Hydronic pressure; authored as {sw}/{sf}/{tw}/{tf} psi/h → kPa/h.",
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
    # Temperature (°F/h authored → stored as °F/h)
    "zone_air_temperature": _t("zone_air_temperature", "zone", 4, 6, 8, 12, extreme=15.0, window=30),
    "return_air_temperature": _t("return_air_temperature", "return", 6, 10, 12, 20),
    "outside_air_temperature": _t("outside_air_temperature", "outside", 12, 18, 20, 30, window=15),
    "mixed_air_temperature": _t("mixed_air_temperature", "mixed", 12, 20, 30, 45, window=15),
    "supply_air_temperature": _t("supply_air_temperature", "supply", 10, 16, 35, 50, window=20),
    "heating_coil_leaving_air_temperature": _t(
        "heating_coil_leaving_air_temperature", "heating_coil_leave", 15, 25, 50, 75, window=10
    ),
    "cooling_coil_leaving_air_temperature": _t(
        "cooling_coil_leaving_air_temperature", "cooling_coil_leave", 12, 20, 35, 50, window=10
    ),
    "vav_discharge_air_temperature": _t(
        "vav_discharge_air_temperature", "vav_discharge", 12, 20, 35, 50
    ),
    "chilled_water_supply_temperature": _t(
        "chilled_water_supply_temperature", "chw_supply", 6, 10, 15, 25, window=30
    ),
    "chilled_water_return_temperature": _t(
        "chilled_water_return_temperature", "chw_return", 8, 12, 15, 25, window=30
    ),
    "hot_water_supply_temperature": _t(
        "hot_water_supply_temperature", "hw_supply", 15, 25, 50, 75, window=30
    ),
    "hot_water_return_temperature": _t(
        "hot_water_return_temperature", "hw_return", 12, 20, 30, 50, window=30
    ),
    "condenser_water_temperature": _t(
        "condenser_water_temperature", "cw", 10, 16, 20, 30, window=20
    ),
    "refrigerant_temperature": _t(
        "refrigerant_temperature", "refrigerant", 40, 75, 150, 250, window=15
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
    # Air pressure (authored in.w.c./h)
    "building_static_pressure": _air_p("building_static_pressure", "building", 0.10, 0.20, 0.30, 0.50),
    "duct_static_pressure": _air_p("duct_static_pressure", "duct", 0.75, 1.25, 3.00, 5.00),
    "filter_differential_pressure": _air_p("filter_differential_pressure", "filter", 0.25, 0.50, 1.00, 2.00),
    "vav_differential_pressure": _air_p("vav_differential_pressure", "vav_dp", 0.50, 1.00, 2.00, 4.00),
    # Hydronic (authored psi/h)
    "hydronic_differential_pressure": _hyd_p("hydronic_differential_pressure", "hydronic_dp", 5, 10, 20, 35),
    "pump_pressure": _hyd_p("pump_pressure", "pump", 10, 20, 40, 60),
    "static_hydronic_pressure": _hyd_p("static_hydronic_pressure", "hydronic_static", 3, 6, 10, 20),
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
