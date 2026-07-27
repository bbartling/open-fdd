from __future__ import annotations
from math import isfinite
from typing import Any
from .registry import get, names, register

def _req(data: dict[str, Any], key: str) -> float:
    if key not in data:
        raise ValueError(f"missing required input: {key}")
    value = float(data[key])
    if not isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value

def _positive(data: dict[str, Any], key: str) -> float:
    value = _req(data, key)
    if value <= 0:
        raise ValueError(f"{key} must be > 0")
    return value

@register("fan_affinity")
def fan_affinity(i: dict[str, Any]) -> dict[str, Any]:
    design_kw = _positive(i, "design_kw")
    hours = max(0.0, _req(i, "hours"))
    baseline_speed = _req(i, "baseline_speed_fraction")
    proposed_speed = _req(i, "proposed_speed_fraction")
    exponent = float(i.get("power_exponent", 3.0))
    baseline_kwh = design_kw * baseline_speed**exponent * hours
    proposed_kwh = design_kw * proposed_speed**exponent * hours
    return {
        "baseline_kwh": baseline_kwh,
        "proposed_kwh": proposed_kwh,
        "savings_kwh": baseline_kwh - proposed_kwh,
        "assumptions": {"power_exponent": exponent},
    }

@register("schedule_reduction")
def schedule_reduction(i: dict[str, Any]) -> dict[str, Any]:
    kw = _positive(i, "equipment_kw")
    baseline_hours = max(0.0, _req(i, "baseline_annual_hours"))
    proposed_hours = max(0.0, _req(i, "proposed_annual_hours"))
    load = float(i.get("average_load_fraction", 1.0))
    baseline = kw * baseline_hours * load
    proposed = kw * proposed_hours * load
    return {
        "baseline_kwh": baseline,
        "proposed_kwh": proposed,
        "savings_kwh": baseline - proposed,
        "reduced_hours": baseline_hours - proposed_hours,
    }

@register("boiler_efficiency_improvement")
def boiler_efficiency(i: dict[str, Any]) -> dict[str, Any]:
    load = max(0.0, _req(i, "annual_heating_mmbtu"))
    baseline_eff = _positive(i, "baseline_efficiency")
    proposed_eff = _positive(i, "proposed_efficiency")
    baseline_therms = load * 10.0 / baseline_eff
    proposed_therms = load * 10.0 / proposed_eff
    return {
        "baseline_therms": baseline_therms,
        "proposed_therms": proposed_therms,
        "savings_therms": baseline_therms - proposed_therms,
    }

@register("kw_per_ton_improvement")
def kw_per_ton(i: dict[str, Any]) -> dict[str, Any]:
    ton_hours = max(0.0, _req(i, "annual_ton_hours"))
    baseline = _positive(i, "baseline_kw_per_ton")
    proposed = _positive(i, "proposed_kw_per_ton")
    return {
        "baseline_kwh": ton_hours * baseline,
        "proposed_kwh": ton_hours * proposed,
        "savings_kwh": ton_hours * (baseline - proposed),
    }

@register("outside_air_sensible")
def outside_air_sensible(i: dict[str, Any]) -> dict[str, Any]:
    cfm = max(0.0, _req(i, "outside_air_cfm"))
    delta_t = max(0.0, _req(i, "average_delta_t_f"))
    hours = max(0.0, _req(i, "hours"))
    efficiency = float(i.get("system_efficiency", 1.0))
    fuel = str(i.get("fuel", "natural_gas")).lower()
    if efficiency <= 0:
        raise ValueError("system_efficiency must be > 0")
    load_btu = 1.08 * cfm * delta_t * hours
    input_btu = load_btu / efficiency
    result = {"load_btu": load_btu, "input_btu": input_btu}
    if fuel == "natural_gas":
        result["savings_therms"] = input_btu / 100000.0
    elif fuel == "electric":
        result["savings_kwh"] = input_btu / 3412.142
    else:
        raise ValueError("fuel must be natural_gas or electric")
    return result

@register("outside_air_total_cooling")
def outside_air_total_cooling(i: dict[str, Any]) -> dict[str, Any]:
    cfm = max(0.0, _req(i, "outside_air_cfm"))
    delta_h = max(0.0, _req(i, "average_delta_h_btu_lb"))
    hours = max(0.0, _req(i, "hours"))
    cop = _positive(i, "cooling_cop")
    load_mmbtu = 4.5 * cfm * delta_h * hours / 1_000_000.0
    return {
        "load_mmbtu": load_mmbtu,
        "savings_kwh": load_mmbtu * 293.07107 / cop,
    }

@register("economizer_runtime_cap")
def economizer_runtime_cap(i: dict[str, Any]) -> dict[str, Any]:
    observed = max(0.0, _req(i, "observed_mechanical_cooling_hours"))
    eligible = max(0.0, _req(i, "additional_eligible_hours"))
    realization = _req(i, "realization_fraction")
    tons = max(0.0, _req(i, "cooling_tons"))
    load = max(0.0, _req(i, "average_load_fraction"))
    kwpt = _positive(i, "kw_per_ton")
    if not 0 <= realization <= 1:
        raise ValueError("realization_fraction must be 0..1")
    displaced = min(observed, eligible) * realization
    return {
        "displaced_hours": displaced,
        "savings_kwh": displaced * tons * load * kwpt,
    }

@register("chws_reset_proxy")
def chws_reset_proxy(i: dict[str, Any]) -> dict[str, Any]:
    base = max(0.0, _req(i, "baseline_chiller_kwh"))
    reset = max(0.0, _req(i, "weighted_reset_f"))
    gain = max(0.0, _req(i, "efficiency_gain_fraction_per_f"))
    realization = float(i.get("realization_fraction", 1.0))
    pump = float(i.get("pump_kwh_savings", 0.0))
    chiller = base * reset * gain * realization
    return {
        "chiller_savings_kwh": chiller,
        "pump_savings_kwh": pump,
        "savings_kwh": chiller + pump,
        "warning": "Use manufacturer performance data for client-grade analysis.",
    }

@register("condenser_water_proxy")
def condenser_water_proxy(i: dict[str, Any]) -> dict[str, Any]:
    base = max(0.0, _req(i, "baseline_chiller_kwh"))
    reduction = max(0.0, _req(i, "weighted_cw_reduction_f"))
    gain = max(0.0, _req(i, "chiller_gain_fraction_per_f"))
    tower_base = max(0.0, _req(i, "baseline_tower_kwh"))
    tower_prop = max(0.0, _req(i, "proposed_tower_kwh"))
    pump = float(i.get("pump_kwh_savings", 0.0))
    chiller = base * reduction * gain
    tower = tower_base - tower_prop
    return {
        "chiller_savings_kwh": chiller,
        "tower_savings_kwh": tower,
        "pump_savings_kwh": pump,
        "savings_kwh": chiller + tower + pump,
        "warning": "Use chiller/tower performance maps for client-grade analysis.",
    }

def calculate(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return get(name)(inputs)

def list_calculators() -> list[str]:
    return names()
