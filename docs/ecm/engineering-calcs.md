---
title: Engineering calcs
parent: PyPI agent tools
nav_order: 2
permalink: /ecm/engineering-calcs.html
---

# Engineering calculations (agent → Excel)

Complete catalog of **industry-method ECM screens** and **Python referee calculators** in `open_fdd.ecm_engineering`. Agents fill **input cells only**; Excel keeps live formulas. Product FDD remains DataFusion on GHCR.

Install: `pip install open-fdd` (extras: `[oracle]`, `[analytics]`, `[reporting]`).

**Story:** [Purpose — Excel + EnergyPlus]({{ site.baseurl }}/ecm/purpose-excel-energyplus.html) · **Agent context:** [AI agents & skills]({{ site.baseurl }}/ecm/agent-context.html)

```python
from open_fdd.ecm_engineering import ECMJob, list_ecm_modules, list_calculators, calculate

list_ecm_modules()     # 40 workbook modules (aliases for add_ecm)
list_calculators()     # 9 independent Python benchmarks (job.calc / calculate)
```

---

## Finance helpers (always available)

| Helper | Purpose |
|--------|---------|
| `simple_payback(cost, annual_savings)` | Years to recover first cost |
| `npv(rate, cashflows)` | Discounted cash-flow NPV |
| Site globals on `ECMJob.set_global(...)` | `electric_rate`, `gas_rate`, `area_ft2`, demand charges, etc. for $ and **EUI** context in the workbook |

**EUI / intensity:** supply `area_ft2` (and meter / fuel totals from evidence) as globals; intensity and $/ft² columns are formula-driven in the packaged workbook — do not invent floor area.

---

## Workbook ECM modules (`add_ecm` / `list_ecm_modules`)

Friendly alias → sheet name → typical agent input keys (FIELD_ALIASES). Modules with empty keys still exist as workbook sheets — open the template after `save()`.

| Alias (`add_ecm`) | Workbook sheet | Inputs |
|-------------------|----------------|--------|
| `ahu_sched_align` | `ECM_Schedule_Align` | `cool_bin_hours`, `cost`, `current_weekly_h`, `fan_kw`, `fan_run_hours`, `future_weekly_h`, `hours_saved`, `kw_per_ton`, `oad_tons_delta`, `override_pad`, `plant_kw`, `sched_hours_saved`, `tons_base`, `warmup_cooldown_h` |
| `boiler_replace` | `ECM_Boiler_Replace` | `cost`, `load`, `new_eff`, `old_eff`, `therms` |
| `boiler_reset` | `ECM_Boiler_Reset` | `base_eff`, `base_therms`, `cost`, `prop_eff`, `pump_kwh` |
| `capacity_screen` | `HVAC_Capacity_Screen` | _(sheet inputs in workbook template)_ |
| `chiller_lockout` | `ECM_Chiller_Lockout` | `cost`, `hours`, `kw_per_ton`, `lockout_hours`, `lockout_oat_f`, `oat_f`, `plant_kw`, `tons` |
| `chw_reset` | `ECM_CHW_Reset` | `base_kwh`, `cost`, `gain_per_f`, `pump_kwh`, `realization`, `reset_f` |
| `condenser_water_reset` | `ECM_CW_Reset` | `chiller_gain_per_f`, `chiller_kwh`, `cost`, `cw_reduction_f`, `pump_kwh`, `tower_base_kwh`, `tower_prop_kwh` |
| `cooling_schedule` | `ECM_Cool_Schedule` | `cost`, `hours`, `kw_per_ton`, `load_frac`, `tons` |
| `dat_reset` | `ECM_DAT_Reset` | `cool_kwh`, `cost`, `gain_per_f`, `realization`, `reset_f` |
| `dcv` | `ECM_DCV` | `cool_dh`, `cool_frac`, `cop`, `cost`, `heat_dt`, `heat_eff`, `heat_frac`, `hours`, `oa_cfm`, `reduction` |
| `dewpoint_economizer` | `ECM_Dewpoint_Econ` | `chiller_hours`, `cost`, `eligible_hours`, `kw_per_ton`, `load_fraction`, `realization`, `tons` |
| `dirty_filter` | `ECM_Dirty_Filter` | `cfm`, `cost`, `dp`, `fan_eff`, `hours`, `motor_eff` |
| `energy_recovery` | `ECM_Energy_Recovery` | `cool_dh`, `cool_hours`, `cop`, `cost`, `dp`, `exchange_cfm`, `fan_eff`, `heat_dt`, `heat_eff`, `heat_hours`, `motor_kw`, `oa_cfm`, `sens_eff` |
| `enthalpy_economizer` | `ECM_Enthalpy_Econ` | `chiller_hours`, `cost`, `eligible_hours`, `kw_per_ton`, `load_fraction`, `realization`, `tons` |
| `exhaust_control` | `ECM_Exhaust_Control` | _(sheet inputs in workbook template)_ |
| `fan_schedule` | `ECM_Fan_Schedule` | `baseline_hours`, `cost`, `fan_kw`, `proposed_hours` |
| `fan_vfd` | `ECM_Fan_VFD` | `baseline_power_fraction`, `cost`, `design_kw`, `flow_fraction`, `hours`, `vfd_eff` |
| `gas_vs_electric` | `ECM_Gas_vs_Electric` | _(sheet inputs in workbook template)_ |
| `heating_schedule` | `ECM_Heat_Schedule` | `cost`, `eff`, `hours`, `load_frac`, `mbh` |
| `hot_water_pipe_reset` | `ECM_HW_Reset_Pipe` | _(sheet inputs in workbook template)_ |
| `hot_water_pump_control` | `ECM_HW_Pump_Control` | _(sheet inputs in workbook template)_ |
| `humidifier` | `ECM_Humidifier` | _(sheet inputs in workbook template)_ |
| `infiltration` | `ECM_Infiltration` | _(sheet inputs in workbook template)_ |
| `lighting` | `ECM_Lighting` | _(sheet inputs in workbook template)_ |
| `lighting_control` | `ECM_Lighting_Control` | _(sheet inputs in workbook template)_ |
| `load_shed` | `ECM_Load_Shed` | `cost`, `delta_f`, `hours`, `kw_fraction`, `loadshed_hours`, `loadshed_kw_fraction`, `plant_kw` |
| `motor_efficiency` | `ECM_Motor_Eff` | _(sheet inputs in workbook template)_ |
| `occupancy_sensors` | `ECM_Occ_Sensors` | `cool_kwh`, `cost`, `fan_hours`, `fan_kw`, `heat_therm` |
| `optimal_start` | `ECM_Optimal_Start` | `baseline_lead_min`, `cost`, `days`, `fan_kw`, `proposed_lead_min`, `thermal_savings` |
| `pipe_insulation` | `ECM_Pipe_Insulation` | _(sheet inputs in workbook template)_ |
| `pump_vfd` | `ECM_Pump_VFD` | `baseline_power_fraction`, `cost`, `design_kw`, `flow_fraction`, `hours`, `vfd_eff` |
| `return_fan` | `ECM_Return_Fan` | _(sheet inputs in workbook template)_ |
| `sat_reset` | `ECM_DAT_Reset` | `cool_kwh`, `cost`, `gain_per_f`, `realization`, `reset_f` |
| `schedule_align` | `ECM_Schedule_Align` | `cool_bin_hours`, `cost`, `current_weekly_h`, `fan_kw`, `fan_run_hours`, `future_weekly_h`, `hours_saved`, `kw_per_ton`, `oad_tons_delta`, `override_pad`, `plant_kw`, `sched_hours_saved`, `tons_base`, `warmup_cooldown_h` |
| `static_pressure_reset` | `ECM_Static_Reset` | `baseline_speed`, `cost`, `fan_kw`, `hours`, `proposed_speed`, `realization` |
| `steam_leak` | `ECM_Steam_Leak` | _(sheet inputs in workbook template)_ |
| `unit_heater_fan` | `ECM_Unit_Heater_Fan` | _(sheet inputs in workbook template)_ |
| `unoccupied_oa_cooling` | `ECM_Unocc_OA_Cool` | `cfm`, `cop`, `cost`, `h_oa`, `h_ra`, `hours`, `oa_base`, `oa_prop` |
| `unoccupied_oa_heating` | `ECM_Unocc_OA_Heat` | `cfm`, `cost`, `eff`, `hours`, `oa_base`, `oa_prop`, `oa_t`, `ra_t` |
| `water_source_heat_pump_cooling` | `ECM_WHP_Cooling` | _(sheet inputs in workbook template)_ |

**Count:** **40** modules.

---

## Python referee calculators (`calculate` / `list_calculators`)

Independent of Excel cell formulas — use to cross-check or when no sheet is needed yet.

| Calculator | Required / primary inputs |
|------------|---------------------------|
| `boiler_efficiency_improvement` | `baseline_efficiency`, `proposed_efficiency`, `annual_heating_mmbtu` |
| `chws_reset_proxy` | `baseline_chiller_kwh`, `efficiency_gain_fraction_per_f`, `weighted_reset_f` |
| `condenser_water_proxy` | `baseline_chiller_kwh`, `baseline_tower_kwh`, `chiller_gain_fraction_per_f`, `proposed_tower_kwh`, `weighted_cw_reduction_f` |
| `economizer_runtime_cap` | `kw_per_ton`, `additional_eligible_hours`, `average_load_fraction`, `cooling_tons`, `observed_mechanical_cooling_hours`, `realization_fraction` |
| `fan_affinity` | `design_kw`, `baseline_speed_fraction`, `hours`, `proposed_speed_fraction` |
| `kw_per_ton_improvement` | `baseline_kw_per_ton`, `proposed_kw_per_ton`, `annual_ton_hours` |
| `outside_air_sensible` | `average_delta_t_f`, `hours`, `outside_air_cfm` |
| `outside_air_total_cooling` | `cooling_cop`, `average_delta_h_btu_lb`, `hours`, `outside_air_cfm` |
| `schedule_reduction` | `equipment_kw`, `baseline_annual_hours`, `proposed_annual_hours` |

### Fan affinity (static pressure / VFD)

$$
P_{\mathrm{prop}} = P_{\mathrm{base}} \left(\frac{N_{\mathrm{prop}}}{N_{\mathrm{base}}}\right)^{3}
$$

$$
\Delta E \approx (P_{\mathrm{base}} - P_{\mathrm{prop}}) \times h
$$

Module: `static_pressure_reset` · Calculator: `fan_affinity`.

### Boiler / heating efficiency

$$
\Delta \mathrm{therms} \approx Q_{\mathrm{base}} \left(1 - \frac{\eta_{\mathrm{base}}}{\eta_{\mathrm{prop}}}\right)
$$

Modules: `boiler_reset`, `boiler_replace` · Calculator: `boiler_efficiency_improvement`.

### Outside-air sensible / total cooling

Sensible: $$1.08 \times \mathrm{CFM} \times \Delta T \times h$$ (÷ efficiency → therms or kWh).  
Latent/total cooling: $$4.5 \times \mathrm{CFM} \times \Delta h \times h$$ → kWh via COP.

Calculators: `outside_air_sensible`, `outside_air_total_cooling` · Modules: `dcv`, `energy_recovery`, `unoccupied_oa_*`.

### Economizer runtime / CHW / CW proxies

Calculators: `economizer_runtime_cap`, `chws_reset_proxy`, `condenser_water_proxy`, `kw_per_ton_improvement`, `schedule_reduction`. Prefer manufacturer curves for client-grade chiller/tower work.

### Schedule / opt-start / DAT / DSP / lighting / motors / WSHP

See module table above (`schedule_align`, `optimal_start`, `dat_reset`/`sat_reset`, `static_pressure_reset`, `lighting*`, `motor_efficiency`, `water_source_heat_pump_cooling`, …). Exact cell maps live in the packaged `.xlsx` template.

---

## Honesty vs EnergyPlus

- Compare sheet kWh / therms to `ep_*` results after `attach_twin_compare`.
- Label **FITTED** if hours were reverse-fitted; **NO_EP** when no patch; **FAIL_SIGN** is a model/measure problem.
- Never greenwash fitted exact matches as independent BALLPARK.

### IPMVP change-point / G14 (Wave S3 oracle)

Pandas helpers (not product HTTP): `score_g14_monthly`, `fit_changepoint`, `select_changepoint`,
`option_c_savings` — see [IPMVP change-point & G14]({{ site.baseurl }}/ecm/ipmvp-changepoint.html).

Full workflow: [Purpose — Excel + EnergyPlus]({{ site.baseurl }}/ecm/purpose-excel-energyplus.html) · [AI agents & skills]({{ site.baseurl }}/ecm/agent-context.html).

## Related skills (repo)

| Need | Skill |
|------|-------|
| ECM workbook | [`openfdd-ecm-engineering`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-ecm-engineering/SKILL.md) |
| Package / Haystack map | [`openfdd-package-mapping`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-package-mapping/SKILL.md) |
| SQL FDD | [`openfdd-sql-fdd`](https://github.com/bbartling/open-fdd/blob/master/openfdd_agent_spec/skills/openfdd-sql-fdd/SKILL.md) |
