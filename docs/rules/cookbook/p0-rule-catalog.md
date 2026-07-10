---
title: P0 rule catalog (metadata)
parent: Rule Cookbook
nav_order: 11
---

# P0 rule catalog — full metadata

Standards-first metadata for every shipped cookbook rule. Detection SQL/Pandas live in the [SQL](datafusion-sql-cookbook.html) and [Pandas](pandas-cookbook.html) cookbooks. P2 rules: [extended P2 section](datafusion-sql-cookbook.html#extended-rule-families-p2).

{: .important }
All **thresholds are defaults** — site-adjustable. **confirmation_seconds** default **300** unless noted.

---

## Sensor validation

| id | taxonomy_path | equipment | severity | required_points | confirmation_s | root_cause_candidates |
|----|---------------|-----------|----------|-----------------|----------------|----------------------|
| SV-1 | sensor.quality.vav.zone_range | vav | 2 | zone_t, occ_mode | 300 | Bad sensor, miscalibrated zone T |
| SV-2 | sensor.quality.site.oa_range | ahu | 2 | oa_t | 300 | OA sensor fault, exposure issue |
| SV-3 | sensor.quality.site.oa_humidity | ahu | 2 | oa_h | 300 | Humidity sensor drift |
| SV-4 | sensor.quality.ahu.mixing_envelope | ahu | 2 | mat, oat, rat | 300 | MAT sensor, mixed damper fault |
| SV-5 | sensor.quality.site.stale_data | site | 3 | timestamp | 300 | Poll failure, historian gap |
| SV-6 | sensor.quality.generic.flatline_roc | site | 2 | (per rule) | 300 | Stuck sensor, comm loss |
| SV-7 | sensor.quality.generic.wrong_units | site | 2 | (per rule) | 300 | Scaling error in BAS export |

---

## AHU FC1–FC15 (GL36-aligned)

| id | taxonomy_path | severity | required_points | confirmation_s | recommended_action |
|----|---------------|----------|-----------------|----------------|-------------------|
| FC1 | control.loop.ahu.duct_static_low | 3 | duct_static, duct_static_sp, fan_cmd | 300 | Check fan VFD, duct leaks, SP sensor |
| FC2 | safety.envelope.ahu.mat_below_mix | 2 | mat, oat, rat, fan_cmd | 600 | Verify MAT/OAT/RAT sensors, damper |
| FC3 | safety.envelope.ahu.mat_above_mix | 2 | mat, oat, rat, fan_cmd | 600 | Same as FC2 |
| FC4 | control.loop.ahu.pid_hunting | 2 | htg_valve_pct, clg_valve_pct, fan_cmd, oa_damper_pct | 3600 | Tune PID, check hunting loops |
| FC5 | control.loop.ahu.sat_cold_heating | 3 | sat, htg_valve_pct, fan_cmd | 300 | Heating valve, SAT sensor |
| FC6 | ventilation.ahu.oa_fraction_mismatch | 2 | mat, rat, oat, fan_cmd | 300 | Economizer, OA damper |
| FC7 | control.loop.ahu.sat_low_full_heat | 3 | sat, htg_valve_pct, fan_cmd | 300 | Heating capacity, valve |
| FC8 | economizer.ahu.sat_above_blend_econ | 2 | sat, oat, rat, mat, fan_cmd | 300 | Economizer control |
| FC9 | economizer.ahu.oat_too_warm_free_cool | 2 | oat, clg_valve_pct, oa_damper_pct | 300 | Economizer lockout setpoints |
| FC10 | economizer.ahu.oat_mat_mismatch_mech | 2 | oat, mat, clg_valve_pct | 300 | MAT sensor, economizer |
| FC11 | economizer.ahu.oat_mat_mismatch_econ | 2 | oat, mat, oa_damper_pct | 300 | Same as FC10 |
| FC12 | control.loop.ahu.sat_above_blend_cool | 2 | sat, oat, rat, clg_valve_pct | 300 | Cooling/economizer sequencing |
| FC13 | control.loop.ahu.sat_above_sp_full_cool | 3 | sat, sat_sp, clg_valve_pct, fan_cmd | 300 | Cooling capacity, SAT SP |
| FC14 | actuator.leakage.ahu.chw_coil_inactive | 2 | chw_valve_pct, sat, sat_sp | 300 | CHW valve leakage |
| FC15 | actuator.leakage.ahu.hw_coil_inactive | 2 | htg_valve_pct, sat, sat_sp | 300 | HW valve leakage |

---

## AHU auxiliary · VAV · economizer · plant · HP · WX · TRIM · v2

| id | taxonomy_path | equipment | severity | confirmation_s |
|----|---------------|-----------|----------|----------------|
| SAT_DEVIATION | control.loop.ahu.sat_tracking | ahu | 2 | 600 |
| DUCT_STATIC_HIGH | control.loop.ahu.duct_static_high | ahu | 2 | 300 |
| HEAT_COOL_SIMULT | control.loop.ahu.simultaneous_heat_cool | ahu | 3 | 300 |
| FAN_OFF_DUCT_WARM | schedule.ahu.fan_off_warm_duct | ahu | 2 | 600 |
| VAV-1 | terminal.vav.comfort_band | vav | 2 | 900 |
| VAV-2 | schedule.vav.night_setback_miss | vav | 2 | 1800 |
| VAV-3 | terminal.vav.excessive_reheat | vav | 2 | 300 |
| VAV-4 | actuator.leakage.vav.damper_stuck_open | vav | 2 | 900 |
| VAV-5 | terminal.vav.airflow_sensor_bias | vav | 2 | 900 |
| VAV-6 | terminal.vav.reheat_with_cooling | vav | 2 | 300 |
| VAV-7 | terminal.vav.min_airflow_violation | vav | 2 | 900 |
| ECON-1–5 | economizer.ahu.* | ahu | 2 | 300–600 |
| OA-1 | ventilation.ahu.low_oa_fraction | ahu | 2 | 900 |
| OA-2 | ventilation.ahu.dcv_minimum_oa | ahu | 2 | 900 |
| CHW-1–4 | plant.performance.chw.* | plant.chw | 2–3 | 300–900 |
| PLANT-1 | reset.plant.chw.dp_reset_missing | plant.chw | 2 | 900 |
| TOWER-1 | plant.performance.tower.approach_high | plant.tower | 2 | 900 |
| HP-1 | control.loop.hp.discharge_cold | hp | 2 | 600 |
| WX-1–2 | sensor.quality.weather.* | sensor.weather | 2 | 300 |
| TRIM-1–4 | kpi.advisory.* | site | 1 | 1800 |
| RESET-1 | reset.ahu.sat_oa_reset_missing | ahu | 2 | 900 |
| SCHED-1 | schedule.ahu.unoccupied_runtime | ahu | 2 | 1800 |
| OVR-1 | override.ahu.persistent_manual | ahu | 2 | 3600 |
| CMD-1 | command.status.ahu.fan_cmd_status | ahu | 3 | 600 |
| VLV-1 | actuator.leakage.ahu.clg_valve | ahu | 2 | 900 |
| DMP-1 | actuator.leakage.ahu.oa_damper | ahu | 2 | 900 |
| SP-HIGH / SP-LOW | reset.vav.occupied_sp_drift | vav | 2 | 900 |
| CTRL-2 | control.loop.generic.hunting | ahu | 2 | 3600 |
| PID-HUNT-1 | control.loop.generic.output_hunting | ANY | 2 | 0 (1h metrics) |
| KPI-1 | kpi.advisory.site.performance_score | site | 1 | 86400 |

---

## Validation scenarios (all nontrivial rules)

| scenario | expected fault_raw |
|----------|-------------------|
| normal | false |
| obvious_fault | true after confirmation |
| borderline | document sensitivity |
| missing_point | false |
| bad_sensor | false (gated) |
| wrong_units | false or true (SV-7) |

Fixtures: [benchmark strategy](benchmark-strategy.html) · `docs/rules/cookbook/fixtures/`
