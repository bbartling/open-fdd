"""
FDD-oriented energy / savings preview calculations (interval-style inputs annualized).

Outputs align with common M&V-style summaries for dashboards and future fault-duration integration.
Not a full 223P model — plain engineering formulas with explicit assumptions.
"""

from __future__ import annotations

import math
from typing import Any, Optional

# --- Calc type registry (API + UI) -------------------------------------------------

CALC_TYPE_SPECS: dict[str, dict[str, Any]] = {
    "runtime_electric_kw": {
        "label": "Excess runtime — known kW",
        "summary": "kWh = kW × excess hours; for fans/pumps when measured or assumed load is constant.",
        "category": "electric_runtime",
        "fields": [
            {"key": "kw", "label": "Load (kW)", "type": "float", "min": 0},
            {"key": "hours_fault", "label": "Excess hours (e.g. per year)", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "motor_hp_runtime": {
        "label": "Motor HP — runtime savings",
        "summary": "kW = (HP × 0.746 × load_factor) / η_motor; then kWh = kW × hours.",
        "category": "electric_runtime",
        "fields": [
            {"key": "motor_hp", "label": "Motor HP", "type": "float", "min": 0},
            {"key": "load_factor", "label": "Load factor (0–1)", "type": "float", "min": 0, "max": 1, "default": 0.8},
            {"key": "motor_efficiency", "label": "Motor efficiency (0–1)", "type": "float", "min": 0.01, "max": 1, "default": 0.9},
            {"key": "hours_fault", "label": "Excess hours (e.g. per year)", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "vfd_affinity_cube": {
        "label": "Fan / pump VFD (affinity cube)",
        "summary": "ΔkW ≈ P_full × ((S_base/100)³ − (S_prop/100)³); annual kWh = ΔkW × hours.",
        "category": "vfd_affinity",
        "fields": [
            {"key": "p_full_kw", "label": "Power at full speed (kW)", "type": "float", "min": 0},
            {"key": "speed_base_pct", "label": "Baseline speed (%)", "type": "float", "min": 0, "max": 150, "default": 100},
            {"key": "speed_prop_pct", "label": "Improved speed (%)", "type": "float", "min": 0, "max": 150, "default": 70},
            {"key": "hours", "label": "Operating hours in fault/improved scenario", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "oa_heating_sensible": {
        "label": "Excess OA — heating (sensible)",
        "summary": "BTU/h ≈ 1.08 × CFM × ΔT; therms ≈ BTU × hours / (100,000 × η).",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm_excess", "label": "Excess OA CFM", "type": "float", "min": 0},
            {"key": "delta_t_f", "label": "ΔT (°F) heating", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours in condition", "type": "float", "min": 0},
            {"key": "heating_efficiency", "label": "Heating efficiency (0–1)", "type": "float", "min": 0.01, "max": 1, "default": 0.8},
            {"key": "therm_rate_usd", "label": "Gas rate ($/therm)", "type": "float", "min": 0, "default": 1.0},
        ],
    },
    "oa_cooling_sensible": {
        "label": "Excess OA — cooling (sensible)",
        "summary": "BTU/h ≈ 1.08 × CFM × ΔT; kWh ≈ BTU × hours / (3412 × COP).",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm_excess", "label": "Excess OA CFM", "type": "float", "min": 0},
            {"key": "delta_t_f", "label": "ΔT (°F) cooling (OA vs reference)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours in condition", "type": "float", "min": 0},
            {"key": "cop", "label": "Plant / chiller COP", "type": "float", "min": 0.1, "default": 3.5},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "simultaneous_hydronic_btu": {
        "label": "Simultaneous heat + cool — hydronic waste",
        "summary": "BTU/h ≈ 500 × GPM × ΔT (water); useful for reheat / fighting coils.",
        "category": "hydronic_waste",
        "fields": [
            {"key": "gpm", "label": "Flow (GPM)", "type": "float", "min": 0},
            {"key": "delta_t_f", "label": "ΔT (°F)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours simultaneous", "type": "float", "min": 0},
            {"key": "assign_to", "label": "Assign fuel", "type": "enum", "options": ["electric_chiller", "gas_boiler"], "default": "electric_chiller"},
            {"key": "cop", "label": "COP (if electric assign)", "type": "float", "min": 0.1, "default": 3.5},
            {"key": "boiler_efficiency", "label": "Boiler η (if gas assign)", "type": "float", "min": 0.01, "max": 1, "default": 0.8},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
            {"key": "therm_rate_usd", "label": "Gas rate ($/therm)", "type": "float", "min": 0, "default": 1.0},
        ],
    },
    "lighting_watts": {
        "label": "Lighting — runtime",
        "summary": "kWh = (W/1000) × hours saved.",
        "category": "lighting",
        "fields": [
            {"key": "watts", "label": "Connected load (W)", "type": "float", "min": 0},
            {"key": "hours_saved", "label": "Hours saved (e.g. per year)", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    # --- Penalty catalog / GL36-style extensions ---------------------------------
    "ahu_sat_sensible_waste": {
        "label": "AHU SAT waste (sensible cooling)",
        "summary": "BTU/h ≈ 1.08 × CFM × (SAT_opt − SAT_actual); kWh at COP.",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm", "label": "Supply airflow (CFM)", "type": "float", "min": 0},
            {"key": "sat_opt_f", "label": "SAT optimal (°F)", "type": "float"},
            {"key": "sat_actual_f", "label": "SAT actual (°F)", "type": "float"},
            {"key": "hours", "label": "Hours in fault", "type": "float", "min": 0},
            {"key": "cop", "label": "Cooling COP", "type": "float", "min": 0.1, "default": 3.5},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "pressure_ratio_motor_kw": {
        "label": "Fan or pump — pressure ratio waste",
        "summary": "ΔkW ≈ kW_act × (1 − (P_opt/P_act)^1.5).",
        "category": "vfd_affinity",
        "fields": [
            {"key": "kw_actual", "label": "Motor kW (actual)", "type": "float", "min": 0},
            {"key": "p_actual", "label": "Pressure / DP actual", "type": "float", "min": 0.001},
            {"key": "p_opt", "label": "Pressure / DP optimal", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "sensible_coil_leak_kw": {
        "label": "Coil leak — sensible BTU to compressor kW",
        "summary": "BTU/h ≈ 1.08 × CFM × ΔT_coil; kWh = BTU×h/(3412×COP).",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm", "label": "Airflow (CFM)", "type": "float", "min": 0},
            {"key": "delta_t_coil_f", "label": "ΔT across coil (°F)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {"key": "cop", "label": "Cooling COP", "type": "float", "min": 0.1, "default": 3.5},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "fan_filter_dp_kw": {
        "label": "Filter/coil — extra fan kW (inWC)",
        "summary": "kW ≈ CFM × ΔP / (6356 η_fan η_motor) × 0.746.",
        "category": "electric_runtime",
        "fields": [
            {"key": "cfm", "label": "Airflow (CFM)", "type": "float", "min": 0},
            {"key": "delta_p_excess_inwc", "label": "Excess ΔP (in w.c.)", "type": "float", "min": 0},
            {"key": "eta_fan", "label": "Fan efficiency (0–1)", "type": "float", "min": 0.01, "max": 1, "default": 0.65},
            {"key": "eta_motor", "label": "Motor efficiency (0–1)", "type": "float", "min": 0.01, "max": 1, "default": 0.92},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "missed_economizer_cooling": {
        "label": "Missed economizer (sensible)",
        "summary": "Q ≈ 1.08 × CFM × (T_return − T_outside); kWh at COP.",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm", "label": "Mixed / supply airflow (CFM)", "type": "float", "min": 0},
            {"key": "t_return_f", "label": "Return air (°F)", "type": "float"},
            {"key": "t_outside_f", "label": "Outside air (°F)", "type": "float"},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {"key": "cop", "label": "Cooling COP", "type": "float", "min": 0.1, "default": 3.5},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "enthalpy_wheel_proxy": {
        "label": "ERV wheel deficit (enthalpy proxy)",
        "summary": "BTU/h ≈ 4.5 × CFM_OA × Δh (h in BTU/lb).",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm_oa", "label": "Outside air CFM", "type": "float", "min": 0},
            {"key": "delta_h_ft_lb_per_lb", "label": "Δh (BTU/lb)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {"key": "cop", "label": "Cooling COP (if cooling)", "type": "float", "min": 0.1, "default": 3.5},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "zone_simultaneous_sensible": {
        "label": "Zone simultaneous heat + cool (sensible)",
        "summary": "Annualizes opposing BTU/h streams to $ (electric COP vs gas η).",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm", "label": "Zone airflow (CFM)", "type": "float", "min": 0},
            {"key": "q_cool_btu_h", "label": "Cooling delivered (BTU/h)", "type": "float", "min": 0},
            {"key": "q_heat_btu_h", "label": "Heating delivered (BTU/h)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours hunting", "type": "float", "min": 0},
            {"key": "cop", "label": "Cooling COP", "type": "float", "min": 0.1, "default": 3.5},
            {"key": "heating_efficiency", "label": "Heating η (gas)", "type": "float", "min": 0.01, "max": 1, "default": 0.8},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
            {"key": "therm_rate_usd", "label": "Gas rate ($/therm)", "type": "float", "min": 0, "default": 1.0},
            {
                "key": "assign_cooling_to",
                "label": "Cooling fuel",
                "type": "enum",
                "options": ["electric", "gas"],
                "default": "electric",
            },
        ],
    },
    "vav_min_flow_reheat": {
        "label": "VAV min flow — reheat waste",
        "summary": "BTU/h ≈ 1.08 × ΔCFM × (T_zone − T_supply); therms at η.",
        "category": "airside_thermal",
        "fields": [
            {"key": "cfm_excess", "label": "CFM above minimum", "type": "float", "min": 0},
            {"key": "delta_t_f", "label": "|T_zone − T_supply| (°F)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {"key": "heating_efficiency", "label": "Reheat η", "type": "float", "min": 0.01, "max": 1, "default": 0.8},
            {"key": "therm_rate_usd", "label": "Gas rate ($/therm)", "type": "float", "min": 0, "default": 1.0},
        ],
    },
    "plant_minimum_stack_kw": {
        "label": "Plant minimum kW stack",
        "summary": "E = kW_stack × hours (chiller + pumps at minimum).",
        "category": "electric_runtime",
        "fields": [
            {"key": "kw_stack", "label": "Combined minimum kW", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "boiler_standby_mix": {
        "label": "Boiler / HW standby",
        "summary": "Pump kWh + boiler min firing (therms).",
        "category": "hydronic_waste",
        "fields": [
            {"key": "kw_hw_pump", "label": "HW pump kW", "type": "float", "min": 0},
            {"key": "boiler_min_btu_h", "label": "Boiler minimum firing (BTU/h)", "type": "float", "min": 0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {"key": "boiler_efficiency", "label": "Combustion η", "type": "float", "min": 0.01, "max": 1, "default": 0.8},
            {"key": "therm_rate_usd", "label": "Gas rate ($/therm)", "type": "float", "min": 0, "default": 1.0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "short_cycle_financial": {
        "label": "Short-cycle financial proxy",
        "summary": "$(extra starts) × wear + 10% of energy cost.",
        "category": "electric_runtime",
        "fields": [
            {"key": "starts_per_hour", "label": "Starts per hour", "type": "float", "min": 0},
            {"key": "allowed_starts_per_hour", "label": "Allowed starts/hour", "type": "float", "min": 0, "default": 6},
            {"key": "cost_wear_usd_per_start", "label": "$ per excess start", "type": "float", "min": 0, "default": 25},
            {"key": "kwh_in_period", "label": "kWh over analysis window", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "chwst_reset_penalty_kw": {
        "label": "CHWST reset penalty (rule-of-thumb)",
        "summary": "kW_waste ≈ kW_act × 0.015 × (CHWST_opt − CHWST_act) per °F.",
        "category": "electric_runtime",
        "fields": [
            {"key": "kw_actual", "label": "Chiller kW (actual)", "type": "float", "min": 0},
            {"key": "chwst_opt_f", "label": "CHWST optimal (°F)", "type": "float"},
            {"key": "chwst_actual_f", "label": "CHWST actual (°F)", "type": "float"},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
    "cop_gap_electric": {
        "label": "COP gap — extra compressor kW",
        "summary": "kW_waste = Q × (1/(3.412×COP_a) − 1/(3.412×COP_d)).",
        "category": "electric_runtime",
        "fields": [
            {"key": "q_load_btu_h", "label": "Load (BTU/h)", "type": "float", "min": 0},
            {"key": "cop_actual", "label": "COP actual", "type": "float", "min": 0.1, "default": 4.0},
            {"key": "cop_design", "label": "COP design", "type": "float", "min": 0.1, "default": 6.0},
            {"key": "hours", "label": "Hours", "type": "float", "min": 0},
            {
                "key": "electric_rate_per_kwh",
                "label": "Electric rate ($/kWh)",
                "type": "float",
                "min": 0,
                "default": 0.12,
            },
        ],
    },
}

ALLOWED_CALC_TYPES = frozenset(CALC_TYPE_SPECS.keys())


def _f(params: dict[str, Any], key: str, default: Optional[float] = None) -> Optional[float]:
    if key not in params or params[key] is None or params[key] == "":
        return default
    try:
        return float(params[key])
    except (TypeError, ValueError):
        return None


def _v(params: dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
    """Raw parameter lookup for non-numeric fields (e.g. enum string ids)."""
    if key not in params or params[key] is None or params[key] == "":
        return default
    return params[key]


def _missing_required(spec: dict[str, Any], params: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for f in spec.get("fields") or []:
        if f.get("type") == "enum":
            if _v(params, f["key"], None) is None and f.get("default") is None:
                missing.append(f["key"])
            continue
        v = _f(params, f["key"], None)
        if v is None and f.get("default") is None:
            missing.append(f["key"])
    return missing


def preview_energy_calc(calc_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """
    Return standard preview block. Uses annualized / user-supplied hours (not yet trend-integrated).
    """
    out: dict[str, Any] = {
        "calc_type": calc_type,
        "annual_kwh_saved": None,
        "annual_therms_saved": None,
        "annual_mmbtu_saved": None,
        "annual_cost_saved_usd": None,
        "peak_kw_reduced": None,
        "simple_payback_years": None,
        "confidence_score": None,
        "missing_inputs": [],
        "assumptions_used": [],
        "notes": "Preview uses static inputs; tie to fault duration and trends in a future analytics pass.",
    }
    if calc_type not in CALC_TYPE_SPECS:
        out["notes"] = f"Unknown calc_type {calc_type!r}."
        out["confidence_score"] = 0
        return out

    spec = CALC_TYPE_SPECS[calc_type]
    params = dict(parameters or {})
    for f in spec.get("fields") or []:
        if f.get("default") is not None and (f["key"] not in params or params[f["key"]] in (None, "")):
            params[f["key"]] = f["default"]

    missing = _missing_required(spec, params)
    out["missing_inputs"] = missing
    if missing:
        out["confidence_score"] = 1
        return out

    assumptions: list[str] = [
        "Sensible air only unless noted; no demand-charge model.",
        "Single operating point / annualized hours — not interval-integrated.",
    ]
    out["assumptions_used"] = assumptions

    kwh = 0.0
    therms = 0.0
    cost = 0.0
    peak_kw = None

    if calc_type == "runtime_electric_kw":
        kw = _f(params, "kw", 0) or 0
        h = _f(params, "hours_fault", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kwh = kw * h
        cost = kwh * rate
        peak_kw = kw
    elif calc_type == "motor_hp_runtime":
        hp = _f(params, "motor_hp", 0) or 0
        lf = _f(params, "load_factor", 0.8) or 0.8
        eta = _f(params, "motor_efficiency", 0.9) or 0.9
        h = _f(params, "hours_fault", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kw_m = (hp * 0.746 * lf) / max(eta, 1e-6)
        kwh = kw_m * h
        cost = kwh * rate
        peak_kw = kw_m
        assumptions.append("Motor kW from nameplate HP × load factor / efficiency.")
    elif calc_type == "vfd_affinity_cube":
        p_full = _f(params, "p_full_kw", 0) or 0
        sb = (_f(params, "speed_base_pct", 100) or 100) / 100.0
        sp = (_f(params, "speed_prop_pct", 70) or 70) / 100.0
        h = _f(params, "hours", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kw_saved = p_full * (max(sb, 0) ** 3 - max(sp, 0) ** 3)
        if kw_saved < 0:
            kw_saved = 0.0
        kwh = kw_saved * h
        cost = kwh * rate
        peak_kw = kw_saved
        assumptions.append("Affinity P ∝ speed³; ignores system curve and minimum speed limits.")
    elif calc_type == "oa_heating_sensible":
        cfm = _f(params, "cfm_excess", 0) or 0
        dt = _f(params, "delta_t_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        eta = _f(params, "heating_efficiency", 0.8) or 0.8
        tr = _f(params, "therm_rate_usd", 0) or 0
        btuh = 1.08 * cfm * dt
        btu_tot = btuh * h
        th = btu_tot / (100_000.0 * max(eta, 1e-6))
        therms = th
        cost = th * tr
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
    elif calc_type == "oa_cooling_sensible":
        cfm = _f(params, "cfm_excess", 0) or 0
        dt = _f(params, "delta_t_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        cop = _f(params, "cop", 3.5) or 3.5
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        btuh = 1.08 * cfm * dt
        btu_tot = btuh * h
        kwh = btu_tot / (3412.0 * max(cop, 1e-6))
        cost = kwh * rate
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
    elif calc_type == "simultaneous_hydronic_btu":
        gpm = _f(params, "gpm", 0) or 0
        dt = _f(params, "delta_t_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        assign = str(params.get("assign_to") or "electric_chiller")
        btuh = 500.0 * gpm * dt
        btu_tot = btuh * h
        out["annual_mmbtu_saved"] = btu_tot / 1_000_000.0
        if assign == "gas_boiler":
            eta = _f(params, "boiler_efficiency", 0.8) or 0.8
            tr = _f(params, "therm_rate_usd", 0) or 0
            therms = btu_tot / (100_000.0 * max(eta, 1e-6))
            cost = therms * tr
        else:
            cop = _f(params, "cop", 3.5) or 3.5
            rate = _f(params, "electric_rate_per_kwh", 0) or 0
            kwh = btu_tot / (3412.0 * max(cop, 1e-6))
            cost = kwh * rate
    elif calc_type == "lighting_watts":
        w = _f(params, "watts", 0) or 0
        h = _f(params, "hours_saved", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kwh = (w / 1000.0) * h
        cost = kwh * rate
        peak_kw = w / 1000.0
    elif calc_type == "ahu_sat_sensible_waste":
        cfm = _f(params, "cfm", 0) or 0
        sat_o = _f(params, "sat_opt_f", 0) or 0
        sat_a = _f(params, "sat_actual_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        cop = _f(params, "cop", 3.5) or 3.5
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        d_sat = max(0.0, sat_o - sat_a)
        btuh = 1.08 * cfm * d_sat
        btu_tot = btuh * h
        kwh = btu_tot / (3412.0 * max(cop, 1e-6))
        cost = kwh * rate
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
    elif calc_type == "pressure_ratio_motor_kw":
        kw_a = _f(params, "kw_actual", 0) or 0
        p_a = _f(params, "p_actual", 0) or 0
        p_o = _f(params, "p_opt", 0) or 0
        h = _f(params, "hours", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        ratio = (p_o / max(p_a, 1e-9)) ** 1.5
        ratio = min(ratio, 1.0)
        kw_w = max(0.0, kw_a * (1.0 - ratio))
        kwh = kw_w * h
        cost = kwh * rate
        peak_kw = kw_w
    elif calc_type == "sensible_coil_leak_kw":
        cfm = _f(params, "cfm", 0) or 0
        dt = _f(params, "delta_t_coil_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        cop = _f(params, "cop", 3.5) or 3.5
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        btuh = 1.08 * cfm * dt
        btu_tot = btuh * h
        kwh = btu_tot / (3412.0 * max(cop, 1e-6))
        cost = kwh * rate
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
    elif calc_type == "fan_filter_dp_kw":
        cfm = _f(params, "cfm", 0) or 0
        dp = _f(params, "delta_p_excess_inwc", 0) or 0
        ef = _f(params, "eta_fan", 0.65) or 0.65
        em = _f(params, "eta_motor", 0.92) or 0.92
        h = _f(params, "hours", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kw_fan = (cfm * dp) / (6356.0 * max(ef, 1e-6) * max(em, 1e-6)) * 0.746
        kwh = max(0.0, kw_fan) * h
        cost = kwh * rate
        peak_kw = max(0.0, kw_fan)
    elif calc_type == "missed_economizer_cooling":
        cfm = _f(params, "cfm", 0) or 0
        tr = _f(params, "t_return_f", 0) or 0
        toa = _f(params, "t_outside_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        cop = _f(params, "cop", 3.5) or 3.5
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        dt = max(0.0, tr - toa)
        btuh = 1.08 * cfm * dt
        btu_tot = btuh * h
        kwh = btu_tot / (3412.0 * max(cop, 1e-6))
        cost = kwh * rate
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
    elif calc_type == "enthalpy_wheel_proxy":
        cfm = _f(params, "cfm_oa", 0) or 0
        dh = _f(params, "delta_h_ft_lb_per_lb", 0) or 0
        h = _f(params, "hours", 0) or 0
        cop = _f(params, "cop", 3.5) or 3.5
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        btuh = 4.5 * cfm * dh
        btu_tot = btuh * h
        kwh = btu_tot / (3412.0 * max(cop, 1e-6))
        cost = kwh * rate
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
    elif calc_type == "zone_simultaneous_sensible":
        qc = _f(params, "q_cool_btu_h", 0) or 0
        qh = _f(params, "q_heat_btu_h", 0) or 0
        h = _f(params, "hours", 0) or 0
        cop = _f(params, "cop", 3.5) or 3.5
        heff = _f(params, "heating_efficiency", 0.8) or 0.8
        er = _f(params, "electric_rate_per_kwh", 0) or 0
        tr = _f(params, "therm_rate_usd", 0) or 0
        assign = str(params.get("assign_cooling_to") or "electric")
        btu_tot = (qc + qh) * h
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
        if assign == "electric":
            kwh_c = (qc * h) / (3412.0 * max(cop, 1e-6))
            therms_gas = ((qh * h) / (100_000.0 * max(heff, 1e-6))) if qh else 0.0
        else:
            # Model cooling as gas-fired reheat / absorption-style penalty (therms).
            kwh_c = 0.0
            therms_cool = ((qc * h) / (100_000.0 * max(heff, 1e-6))) if qc else 0.0
            therms_heat = ((qh * h) / (100_000.0 * max(heff, 1e-6))) if qh else 0.0
            therms_gas = therms_cool + therms_heat
        cost = kwh_c * er + therms_gas * tr
        kwh = kwh_c if kwh_c else None
        therms = therms_gas if therms_gas else None
        if assign == "gas":
            kwh = None
        out["annual_kwh_saved"] = round(kwh, 4) if kwh else None
        out["annual_therms_saved"] = round(therms, 6) if therms else None
        out["annual_cost_saved_usd"] = round(cost, 2) if cost else None
        out["confidence_score"] = 2
        return out
    elif calc_type == "vav_min_flow_reheat":
        cfm = _f(params, "cfm_excess", 0) or 0
        dt = _f(params, "delta_t_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        eta = _f(params, "heating_efficiency", 0.8) or 0.8
        trt = _f(params, "therm_rate_usd", 0) or 0
        btuh = 1.08 * cfm * dt
        btu_tot = btuh * h
        th = btu_tot / (100_000.0 * max(eta, 1e-6))
        therms = th
        cost = th * trt
        out["annual_mmbtu_saved"] = (btu_tot / 1_000_000.0) if btu_tot else None
        out["annual_kwh_saved"] = None
        out["annual_therms_saved"] = round(therms, 6) if therms else None
        out["annual_cost_saved_usd"] = round(cost, 2) if cost else None
        out["confidence_score"] = 3
        return out
    elif calc_type == "plant_minimum_stack_kw":
        kws = _f(params, "kw_stack", 0) or 0
        h = _f(params, "hours", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kwh = kws * h
        cost = kwh * rate
        peak_kw = kws
    elif calc_type == "boiler_standby_mix":
        kw_p = _f(params, "kw_hw_pump", 0) or 0
        bmin = _f(params, "boiler_min_btu_h", 0) or 0
        h = _f(params, "hours", 0) or 0
        eta = _f(params, "boiler_efficiency", 0.8) or 0.8
        tr_therm = _f(params, "therm_rate_usd", 0) or 0
        er = _f(params, "electric_rate_per_kwh", 0) or 0
        kwh = kw_p * h
        th = (bmin * h) / (100_000.0 * max(eta, 1e-6))
        cost = kwh * er + th * tr_therm
        therms = th
        out["annual_kwh_saved"] = round(kwh, 4) if kwh else None
        out["annual_therms_saved"] = round(therms, 6) if therms else None
        out["annual_cost_saved_usd"] = round(cost, 2) if cost else None
        out["confidence_score"] = 2
        return out
    elif calc_type == "short_cycle_financial":
        sph = _f(params, "starts_per_hour", 0) or 0
        allow = _f(params, "allowed_starts_per_hour", 6) or 6
        cw = _f(params, "cost_wear_usd_per_start", 25) or 25
        ek = _f(params, "kwh_in_period", 0) or 0
        er = _f(params, "electric_rate_per_kwh", 0) or 0
        extra = max(0.0, sph - allow)
        wear = extra * cw
        energy_pen = ek * er * 0.10
        cost = wear + energy_pen
        out["annual_cost_saved_usd"] = round(cost, 2) if cost else None
        out["annual_kwh_saved"] = None
        out["annual_therms_saved"] = None
        out["confidence_score"] = 1
        return out
    elif calc_type == "chwst_reset_penalty_kw":
        kwa = _f(params, "kw_actual", 0) or 0
        t_o = _f(params, "chwst_opt_f", 0) or 0
        t_a = _f(params, "chwst_actual_f", 0) or 0
        h = _f(params, "hours", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        dt = max(0.0, t_o - t_a)
        kw_w = kwa * 0.015 * dt
        kwh = max(0.0, kw_w) * h
        cost = kwh * rate
        peak_kw = max(0.0, kw_w)
    elif calc_type == "cop_gap_electric":
        q = _f(params, "q_load_btu_h", 0) or 0
        ca = _f(params, "cop_actual", 4.0) or 4.0
        cd = _f(params, "cop_design", 6.0) or 6.0
        h = _f(params, "hours", 0) or 0
        rate = _f(params, "electric_rate_per_kwh", 0) or 0
        kw_a = q / (3412.0 * max(ca, 1e-6))
        kw_d = q / (3412.0 * max(cd, 1e-6))
        kw_w = max(0.0, kw_a - kw_d)
        kwh = kw_w * h
        cost = kwh * rate
        peak_kw = kw_w

    if not math.isfinite(kwh):
        kwh = 0.0
    if not math.isfinite(therms):
        therms = 0.0
    if not math.isfinite(cost):
        cost = 0.0

    if calc_type == "oa_heating_sensible":
        out["annual_kwh_saved"] = None
        out["annual_therms_saved"] = round(therms, 6) if therms else None
    elif calc_type == "simultaneous_hydronic_btu":
        assign_s = str(params.get("assign_to") or "electric_chiller")
        if assign_s == "gas_boiler":
            out["annual_kwh_saved"] = None
            out["annual_therms_saved"] = round(therms, 6) if therms else None
        else:
            out["annual_kwh_saved"] = round(kwh, 4) if kwh else None
            out["annual_therms_saved"] = None
    else:
        out["annual_kwh_saved"] = round(kwh, 4) if kwh else None
        out["annual_therms_saved"] = round(therms, 6) if therms else None

    out["annual_cost_saved_usd"] = round(cost, 2) if cost else None
    out["peak_kw_reduced"] = round(peak_kw, 4) if peak_kw is not None and peak_kw > 0 else None
    out["confidence_score"] = 3
    if calc_type == "vfd_affinity_cube" and _f(params, "p_full_kw"):
        out["confidence_score"] = 4
    elif calc_type == "motor_hp_runtime" and _f(params, "motor_hp"):
        out["confidence_score"] = 4

    return out


def list_calc_types_public() -> list[dict[str, Any]]:
    """Ordered list for API / UI."""
    order = list(CALC_TYPE_SPECS.keys())
    return [
        {"id": k, **{kk: vv for kk, vv in CALC_TYPE_SPECS[k].items() if kk != "fields"}, "fields": CALC_TYPE_SPECS[k]["fields"]}
        for k in order
    ]
