"""Simple 5°F weather-bin benchmark methods modeled after common ESCO practice."""
from __future__ import annotations
from typing import Any
from .weather import OperatingSchedule, WeatherBins, hours_reduction_fraction

MMBTU_PER_THERM = 0.1


def scheduling_fan_bins(*, fan_kw_total: float, existing_schedule: OperatingSchedule, proposed_schedule: OperatingSchedule, bins: WeatherBins) -> dict[str, Any]:
    reduction = hours_reduction_fraction(existing_schedule, proposed_schedule)
    baseline = 0.0
    details = []
    for row in bins.rows:
        hours = existing_schedule.total_operating_hours(row.shift_hours)
        kwh = fan_kw_total * hours
        baseline += kwh
        details.append({"temp_f": row.temp_f, "operating_hours": hours, "baseline_kwh": kwh, "saved_kwh": kwh * reduction})
    savings = baseline * reduction
    return {"baseline_kwh": baseline, "proposed_kwh": baseline - savings, "savings_kwh": savings, "hours_reduction_fraction": reduction, "bins": details}


def scheduling_heating_bins(*, oa_cfm_total: float, boiler_efficiency: float, existing_schedule: OperatingSchedule, proposed_schedule: OperatingSchedule, bins: WeatherBins, balance_point_f: float = 55.0) -> dict[str, Any]:
    if boiler_efficiency <= 0:
        raise ValueError("boiler_efficiency must be > 0")
    reduction = hours_reduction_fraction(existing_schedule, proposed_schedule)
    baseline_mmbtu = 0.0
    details = []
    for row in bins.rows:
        hours = existing_schedule.total_operating_hours(row.shift_hours)
        kbtu_h = max(0.0, 1.08 * oa_cfm_total * (balance_point_f - row.temp_f) / 1000.0)
        mmbtu = kbtu_h * hours / boiler_efficiency / 1000.0
        baseline_mmbtu += mmbtu
        details.append({"temp_f": row.temp_f, "operating_hours": hours, "baseline_mmbtu": mmbtu, "saved_mmbtu": mmbtu * reduction})
    savings = baseline_mmbtu * reduction
    return {"baseline_mmbtu": baseline_mmbtu, "proposed_mmbtu": baseline_mmbtu - savings, "savings_mmbtu": savings, "savings_therms": savings / MMBTU_PER_THERM, "bins": details}


def scheduling_cooling_bins(*, oa_cfm_total: float, kw_per_ton: float, existing_schedule: OperatingSchedule, proposed_schedule: OperatingSchedule, bins: WeatherBins, supply_enthalpy_btu_lb: float = 23.2) -> dict[str, Any]:
    reduction = hours_reduction_fraction(existing_schedule, proposed_schedule)
    baseline = 0.0
    details = []
    for row in bins.rows:
        hours = existing_schedule.total_operating_hours(row.shift_hours)
        ton_h = 0.0 if row.oa_enthalpy is None else max(0.0, oa_cfm_total * (row.oa_enthalpy - supply_enthalpy_btu_lb) * 4.5 / 12000.0)
        kwh = ton_h * hours * kw_per_ton
        baseline += kwh
        details.append({"temp_f": row.temp_f, "operating_hours": hours, "baseline_kwh": kwh, "saved_kwh": kwh * reduction})
    savings = baseline * reduction
    return {"baseline_kwh": baseline, "proposed_kwh": baseline - savings, "savings_kwh": savings, "bins": details}
