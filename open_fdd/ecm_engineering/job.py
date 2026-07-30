from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

from .algorithms import calculate
from .honesty_export import build_honesty_workbook
from .workbook import OpenFDDECMWorkbook

MODULE_ALIASES = {
    "fan_schedule": "ECM_Fan_Schedule",
    "heating_schedule": "ECM_Heat_Schedule",
    "cooling_schedule": "ECM_Cool_Schedule",
    "unoccupied_oa_heating": "ECM_Unocc_OA_Heat",
    "unoccupied_oa_cooling": "ECM_Unocc_OA_Cool",
    "sat_reset": "ECM_DAT_Reset",
    "dat_reset": "ECM_DAT_Reset",
    "static_pressure_reset": "ECM_Static_Reset",
    "enthalpy_economizer": "ECM_Enthalpy_Econ",
    "dewpoint_economizer": "ECM_Dewpoint_Econ",
    "dcv": "ECM_DCV",
    "optimal_start": "ECM_Optimal_Start",
    "energy_recovery": "ECM_Energy_Recovery",
    "hot_water_pump_control": "ECM_HW_Pump_Control",
    "hot_water_pipe_reset": "ECM_HW_Reset_Pipe",
    "boiler_replace": "ECM_Boiler_Replace",
    "boiler_reset": "ECM_Boiler_Reset",
    "chw_reset": "ECM_CHW_Reset",
    "condenser_water_reset": "ECM_CW_Reset",
    "fan_vfd": "ECM_Fan_VFD",
    "pump_vfd": "ECM_Pump_VFD",
    "dirty_filter": "ECM_Dirty_Filter",
    "exhaust_control": "ECM_Exhaust_Control",
    "infiltration": "ECM_Infiltration",
    "motor_efficiency": "ECM_Motor_Eff",
    "pipe_insulation": "ECM_Pipe_Insulation",
    "lighting": "ECM_Lighting",
    "lighting_control": "ECM_Lighting_Control",
    "humidifier": "ECM_Humidifier",
    "steam_leak": "ECM_Steam_Leak",
    "gas_vs_electric": "ECM_Gas_vs_Electric",
    "occupancy_sensors": "ECM_Occ_Sensors",
    "return_fan": "ECM_Return_Fan",
    "unit_heater_fan": "ECM_Unit_Heater_Fan",
    "water_source_heat_pump_cooling": "ECM_WHP_Cooling",
    "capacity_screen": "HVAC_Capacity_Screen",
    "chiller_lockout": "ECM_Chiller_Lockout",
    "load_shed": "ECM_Load_Shed",
    "schedule_align": "ECM_Schedule_Align",
    "ahu_sched_align": "ECM_Schedule_Align",
}

FIELD_ALIASES = {
    "ECM_Static_Reset": {
        "fan_kw": "spr.fan_kw",
        "hours": "spr.hours",
        "baseline_speed": "spr.base_speed",
        "proposed_speed": "spr.prop_speed",
        "realization": "spr.realization",
        "cost": "spr.cost",
    },
    "ECM_Boiler_Reset": {
        "base_therms": "boilrst.base_therms",
        "base_eff": "boilrst.base_eff",
        "prop_eff": "boilrst.prop_eff",
        "pump_kwh": "boilrst.pump_kwh",
        "cost": "boilrst.cost",
    },
    "ECM_Boiler_Replace": {
        "therms": "boilrep.therms",
        "old_eff": "boilrep.old_eff",
        "new_eff": "boilrep.new_eff",
        "cost": "boilrep.cost",
        "load": "boilrep.load",
    },
    "ECM_CHW_Reset": {
        "base_kwh": "chwrst.base_kwh",
        "reset_f": "chwrst.reset_f",
        "gain_per_f": "chwrst.gain_per_f",
        "realization": "chwrst.realization",
        "pump_kwh": "chwrst.pump_kwh",
        "cost": "chwrst.cost",
    },
    "ECM_CW_Reset": {
        "chiller_kwh": "cwrst.ch_kwh",
        "cw_reduction_f": "cwrst.cw_reduction",
        "chiller_gain_per_f": "cwrst.ch_gain",
        "tower_base_kwh": "cwrst.tower_base",
        "tower_prop_kwh": "cwrst.tower_prop",
        "pump_kwh": "cwrst.pump_kwh",
        "cost": "cwrst.cost",
    },
    "ECM_DAT_Reset": {
        "cool_kwh": "dat.cool_kwh",
        "reset_f": "dat.reset_f",
        "gain_per_f": "dat.gain_per_f",
        "realization": "dat.realization",
        "cost": "dat.cost",
    },
    "ECM_Fan_Schedule": {
        "fan_kw": "fan_sched.fan_kw",
        "baseline_hours": "fan_sched.base_hours",
        "proposed_hours": "fan_sched.prop_hours",
        "cost": "fan_sched.cost",
    },
    "ECM_Cool_Schedule": {
        "hours": "cool_sched.hours",
        "tons": "cool_sched.tons",
        "load_frac": "cool_sched.load_frac",
        "kw_per_ton": "cool_sched.kw_per_ton",
        "cost": "cool_sched.cost",
    },
    "ECM_Heat_Schedule": {
        "hours": "heat_sched.hours",
        "mbh": "heat_sched.mbh",
        "load_frac": "heat_sched.load_frac",
        "eff": "heat_sched.eff",
        "cost": "heat_sched.cost",
    },
    "ECM_Optimal_Start": {
        "baseline_lead_min": "os.base_min",
        "proposed_lead_min": "os.prop_min",
        "days": "os.days",
        "fan_kw": "os.fan_kw",
        "thermal_savings": "os.thermal_savings",
        "cost": "os.cost",
    },
    "ECM_Enthalpy_Econ": {
        "chiller_hours": "econ.run_hours",
        "eligible_hours": "econ.eligible_hours",
        "realization": "econ.realization",
        "tons": "econ.tons",
        "load_fraction": "econ.load",
        "kw_per_ton": "econ.kwpt",
        "cost": "econ.cost",
    },
    "ECM_Dewpoint_Econ": {
        "chiller_hours": "dpe.run_hours",
        "eligible_hours": "dpe.hours",
        "realization": "dpe.realization",
        "tons": "dpe.tons",
        "load_fraction": "dpe.load",
        "kw_per_ton": "dpe.kwpt",
        "cost": "dpe.cost",
    },
    "ECM_DCV": {
        "oa_cfm": "dcv.oa_cfm",
        "reduction": "dcv.reduction",
        "hours": "dcv.hours",
        "heat_dt": "dcv.heat_dt",
        "cool_dh": "dcv.cool_dh",
        "heat_frac": "dcv.heat_frac",
        "cool_frac": "dcv.cool_frac",
        "heat_eff": "dcv.heat_eff",
        "cop": "dcv.cop",
        "cost": "dcv.cost",
    },
    "ECM_Energy_Recovery": {
        "oa_cfm": "erv.oa_cfm",
        "exchange_cfm": "erv.exchange_cfm",
        "sens_eff": "erv.sens_eff",
        "heat_dt": "erv.heat_dt",
        "heat_hours": "erv.heat_hours",
        "heat_eff": "erv.heat_eff",
        "cool_dh": "erv.cool_dh",
        "cool_hours": "erv.cool_hours",
        "cop": "erv.cop",
        "dp": "erv.dp",
        "fan_eff": "erv.fan_eff",
        "motor_kw": "erv.motor_kw",
        "cost": "erv.cost",
    },
    "ECM_Occ_Sensors": {
        "fan_kw": "occ.fan_kw",
        "fan_hours": "occ.fan_hours",
        "cool_kwh": "occ.cool_kwh",
        "heat_therm": "occ.heat_therm",
        "cost": "occ.cost",
    },
    "ECM_Unocc_OA_Heat": {
        "cfm": "uoa_h.cfm",
        "oa_base": "uoa_h.oa_base",
        "oa_prop": "uoa_h.oa_prop",
        "ra_t": "uoa_h.ra_t",
        "oa_t": "uoa_h.oa_t",
        "hours": "uoa_h.hours",
        "eff": "uoa_h.eff",
        "cost": "uoa_h.cost",
    },
    "ECM_Unocc_OA_Cool": {
        "cfm": "uoa_c.cfm",
        "oa_base": "uoa_c.oa_base",
        "oa_prop": "uoa_c.oa_prop",
        "h_oa": "uoa_c.h_oa",
        "h_ra": "uoa_c.h_ra",
        "hours": "uoa_c.hours",
        "cop": "uoa_c.cop",
        "cost": "uoa_c.cost",
    },
    "ECM_Fan_VFD": {
        "design_kw": "fvfd.kw",
        "hours": "fvfd.hours",
        "flow_fraction": "fvfd.flow_frac",
        "baseline_power_fraction": "fvfd.base_power_frac",
        "vfd_eff": "fvfd.vfd_eff",
        "cost": "fvfd.cost",
    },
    "ECM_Pump_VFD": {
        "design_kw": "pvfd.kw",
        "hours": "pvfd.hours",
        "flow_fraction": "pvfd.flow_frac",
        "baseline_power_fraction": "pvfd.base_frac",
        "vfd_eff": "pvfd.vfd_eff",
        "cost": "pvfd.cost",
    },
    "ECM_Dirty_Filter": {
        "cfm": "filter.cfm",
        "dp": "filter.dp",
        "fan_eff": "filter.fan_eff",
        "motor_eff": "filter.motor_eff",
        "hours": "filter.hours",
        "cost": "filter.cost",
    },
    "ECM_Chiller_Lockout": {
        "plant_kw": "lockout.plant_kw",
        "tons": "lockout.tons",
        "kw_per_ton": "lockout.kw_per_ton",
        "lockout_hours": "lockout.hours",
        "hours": "lockout.hours",
        "lockout_oat_f": "lockout.oat_f",
        "oat_f": "lockout.oat_f",
        "cost": "lockout.cost",
    },
    "ECM_Load_Shed": {
        "plant_kw": "loadshed.plant_kw",
        "kw_fraction": "loadshed.kw_fraction",
        "loadshed_kw_fraction": "loadshed.kw_fraction",
        "hours": "loadshed.hours",
        "loadshed_hours": "loadshed.hours",
        "delta_f": "loadshed.delta_f",
        "cost": "loadshed.cost",
    },
    "ECM_Schedule_Align": {
        "fan_kw": "sched.fan_kw",
        "plant_kw": "sched.plant_kw",
        "sched_hours_saved": "sched.hours_saved",
        "hours_saved": "sched.hours_saved",
        "cost": "sched.cost",
        "current_weekly_h": "sched.current_weekly_h",
        "future_weekly_h": "sched.future_weekly_h",
        "override_pad": "sched.override_pad",
        "warmup_cooldown_h": "sched.warmup_cooldown_h",
        "tons_base": "sched.tons_base",
        "cool_bin_hours": "sched.cool_bin_hours",
        "kw_per_ton": "sched.kw_per_ton",
        "fan_run_hours": "sched.fan_run_hours",
        "oad_tons_delta": "sched.oad_tons_delta",
    },
}


def list_ecm_modules() -> list[str]:
    """Friendly ``ECMJob.add_ecm`` names (not ``list_calculators()`` / ``calculate()``)."""
    return sorted(MODULE_ALIASES)

def _slug(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return clean.strip("_") or "open_fdd_ecm_job"

@dataclass
class ECMJob:
    name: str
    path: str | Path | None = None
    _book: OpenFDDECMWorkbook = field(init=False, repr=False)
    _modules: list[str] = field(default_factory=list, init=False)
    _twin_compare: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _export_honesty: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = Path(f"{_slug(self.name)}_ECMs.xlsx")
        else:
            self.path = Path(self.path)
        self._book = OpenFDDECMWorkbook.create(self.path)

    def set_global(
        self,
        *,
        area_ft2: float | None = None,
        electric_rate: float | None = None,
        demand_rate: float | None = None,
        demand_months: int | None = None,
        gas_rate: float | None = None,
        analysis_years: int | None = None,
        discount_rate: float | None = None,
        escalation: float | None = None,
    ) -> "ECMJob":
        values = {
            "global.area_ft2": area_ft2,
            "global.electric_rate": electric_rate,
            "global.demand_rate": demand_rate,
            "global.demand_months": demand_months,
            "global.gas_rate": gas_rate,
            "global.analysis_years": analysis_years,
            "global.discount_rate": discount_rate,
            "global.escalation": escalation,
        }
        self._book.set_many({k: v for k, v in values.items() if v is not None})
        return self

    def add_ecm(
        self,
        name: str,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> "ECMJob":
        module = MODULE_ALIASES.get(name, name)
        if module not in self._book.list_modules():
            raise KeyError(f"unknown ECM {name!r}; available={sorted(MODULE_ALIASES)}")

        supplied = dict(inputs or {})
        supplied.update(kwargs)
        aliases = FIELD_ALIASES.get(module, {})
        available = set(self._book.module_api_keys(module).keys())

        mapped = {}
        for key, value in supplied.items():
            api_key = aliases.get(key, key)
            if api_key not in available:
                raise KeyError(
                    f"unknown input {key!r} for {name!r}; "
                    f"friendly={sorted(aliases)}, api_keys={sorted(available)}"
                )
            mapped[api_key] = value

        if mapped:
            self._book.set_many(mapped)
        if module not in self._modules:
            self._modules.append(module)
        return self

    def attach_twin_compare(self, payload: dict[str, Any]) -> "ECMJob":
        """Attach twin/cascade/G14/demand payload; honesty sheets written on ``save()``."""
        self._twin_compare = dict(payload)
        self._export_honesty = True
        return self

    def export_honesty(self, enabled: bool = True) -> "ECMJob":
        """Request Contents/Measures honesty export on next ``save()`` (even without twin)."""
        self._export_honesty = enabled
        return self

    def calc(self, calculator: str, **inputs: Any) -> dict[str, Any]:
        return calculate(calculator, inputs)

    def selected_modules(self) -> list[str]:
        return list(self._modules)

    def save(self, output_path: str | Path | None = None) -> Path:
        """Return workbook path; copy when ``output_path`` differs.

        Inputs are already flushed by ``set_global`` / ``add_ecm`` (``set_many``).
        ``save()`` and ``save(self.path)`` are idempotent (BUG-OFDD-ECM-002).

        When ``attach_twin_compare`` / ``export_honesty`` is set, writes honesty sheets
        (Contents, Model_Provenance, Inputs, Industry_Screening, Measures, …) to the
        destination path (BUG-OFDD-ECM-009).
        """
        target = Path(output_path) if output_path is not None else Path(self.path)
        if self._export_honesty or self._twin_compare is not None:
            return build_honesty_workbook(
                target,
                twin_payload=self._twin_compare,
                job_name=self.name,
            )
        if output_path is not None:
            return self._book.save_as(output_path)
        return Path(self.path)
