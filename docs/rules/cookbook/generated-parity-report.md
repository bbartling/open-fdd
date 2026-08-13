---
title: Generated parity report
parent: Rule Cookbook
nav_order: 7
---

# Generated parity report

Auto-generated from `sql_rules/generated/parity_inventory.yaml`.
Do not edit by hand. Run `python3 scripts/generate_cookbook_report.py`.

59 is the executable pandas cookbook (CookbookRule constructors). 63 is the SQL registry: those 59 twins plus 4 SQL-only analytics. Aliases SV-SLEW, FC13, and excess_runtime are not extra rules.

- Pandas diagnostics: **59**
- SQL analytics: **4**
- SQL registry: **63**
- Building 100 cartesian: 48 equipment × 59 diagnostics = 2832 results

## Difference classes

| Class | Count |
| --- | ---: |
| `alias` | 3 |
| `intentional_non_applicability` | 4 |
| `missing_implementation` | 1 |
| `none` | 55 |

## Matrix

| rule_id | title | pandas | SQL | parity | class |
| --- | --- | --- | --- | --- | --- |
| `SV-RANGE` | Sensor out of hard range | `sv_range` | `sv_range.sql` | `sql_screening` | `none` |
| `SV-FLATLINE` | Sensor flatline (stuck) | `sv_flatline` | `sv_flatline.sql` | `sql_screening` | `none` |
| `SV-SPIKE` | Sensor rate-of-change spike | `sv_spike` | `sv_spike.sql` | `sql_screening` | `none` |
| `SV-STALE` | Stale data (no fresh samples) | `sv_stale` | `sv_stale.sql` | `sql_screening` | `none` |
| `SV-RATE` | Context-aware sensor rate of change | `sv_rate` | `sv_rate.sql` | `sql_screening` | `alias` |
| `PID-HUNT-1` | Suspected control-output hunting | `pid_hunt_1` | `pid_hunt_1.sql` | `sql_screening` | `none` |
| `FC1` | Duct static below SP at full fan | `fc1` | `fc1_duct_static_low.sql` | `sql_screening` | `none` |
| `FC2` | Mixed air below envelope | `fc2` | `fc2_mat_low.sql` | `sql_screening` | `none` |
| `FC3` | Mixed air above envelope | `fc3` | `fc3_mat_high.sql` | `sql_screening` | `none` |
| `FC4` | PID hunting (operating-state oscillation) | `fc4` | `fc4_os_hunting.sql` | `sql_screening` | `none` |
| `FC5` | SAT cold when heating commanded (GL36 D) | `fc5` | `fc5_sat_cold_heating.sql` | `sql_screening` | `none` |
| `FC6` | Estimated OA fraction mismatch | `fc6` | `fc6_oa_frac_mismatch.sql` | `sql_screening` | `none` |
| `FC7` | SAT low while heating at full | `fc7` | `fc7_sat_low_heating.sql` | `concept_only` | `missing_implementation` |
| `FC8` | SAT vs MAT while economizing | `fc8` | `fc8_sat_mat_econ.sql` | `sql_screening` | `none` |
| `FC9` | OAT high vs SAT SP while economizing | `fc9` | `fc9_oa_sat_sp_econ.sql` | `sql_screening` | `none` |
| `FC10` | MAT-OAT delta while cooling and economizing | `fc10` | `fc10_mat_oa_clg.sql` | `sql_screening` | `none` |
| `FC11` | OAT low vs SAT SP while cooling and economizing | `fc11` | `fc11_oa_sat_sp_clg.sql` | `sql_screening` | `none` |
| `FC12` | SAT above MAT while cooling | `fc12` | `fc12_sat_mat_clg.sql` | `sql_screening` | `none` |
| `FC13` | SAT above setpoint at full cooling | `fc13` | `sat_high_fault.sql` | `sql_screening` | `alias` |
| `FC14` | CHW coil ΔT when inactive (GL36 L) | `fc14` | `fc14_chw_coil_dt_inactive.sql` | `sql_screening` | `none` |
| `FC15` | HW coil ΔT when inactive (GL36 M) | `fc15` | `fc15_hw_coil_dt_inactive.sql` | `sql_screening` | `none` |
| `AHU-SATDEV` | SAT deviation from setpoint | `ahu_satdev` | `ahu_satdev.sql` | `sql_screening` | `none` |
| `AHU-DUCTHI` | Duct static pressure high | `ahu_ducthi` | `ahu_ducthi.sql` | `sql_screening` | `none` |
| `AHU-SIMUL` | Heating and cooling simultaneous | `ahu_simul` | `ahu_simul.sql` | `sql_screening` | `none` |
| `OAT-METEO` | Equipment OAT vs weather-staged wx OAT | `oat_vs_meteo` | `oat_meteo_fault.sql` | `sql_screening` | `none` |
| `ECON-1` | Economizer stuck closed when OAT favorable | `econ1` | `econ1_stuck_closed.sql` | `sql_screening` | `none` |
| `ECON-2` | Economizing when outdoor air unfavorable | `econ2` | `economizer_fault.sql` | `sql_screening` | `none` |
| `ECON-3` | Mech cooling without integrated economizer | `econ_3` | `econ3_mech_without_econ.sql` | `sql_screening` | `none` |
| `ECON-4` | Low estimated OA fraction | `econ4` | `econ4_low_oa_frac.sql` | `sql_screening` | `none` |
| `ECON-5` | Preheat over-conditioning | `econ_5` | `econ5_preheat_over.sql` | `sql_screening` | `none` |
| `ECON-6` | Economizing in freezing weather | `econ_6` | `econ6_econ_freezing.sql` | `sql_screening` | `none` |
| `ECON-7` | Economizer OK but not economizing | `econ_7` | `econ7_ok_not_economizing.sql` | `sql_screening` | `none` |
| `MECH-OAT-1` | Mechanical cooling below 60°F web OAT | `mech_oat_1` | `mech_oat_1.sql` | `sql_screening` | `none` |
| `CHW-NOLOAD-1` | Chiller running with no building load | `chw_noload_1` | `chw_noload_1.sql` | `sql_screening` | `none` |
| `VAV-1` | Zone comfort band violation hours with confirm window | `vav1` | `vav1_comfort_fault.sql` | `sql_screening` | `none` |
| `VAV-3` | Excessive reheat during warm weather | `vav_3` | `vav3_excessive_reheat.sql` | `sql_screening` | `none` |
| `VAV-4` | Damper stuck at full open | `vav_4` | `vav4_damper_full_open.sql` | `sql_screening` | `none` |
| `VAV-5` | Airflow sensor bias | `vav_5` | `vav5_airflow_bias.sql` | `sql_screening` | `none` |
| `VAV-REHEAT` | Reheat valve stuck / no temp rise | `vav_reheat` | `vav_reheat.sql` | `sql_screening` | `none` |
| `VAV-AHU-LEAVE` | VAV leave vs parent AHU SAT (fedBy) | `vav_ahu_leave` | `vav_ahu_leave.sql` | `sql_screening` | `none` |
| `VAV-7` | Min airflow / fixed high flow | `vav_7` | `vav7_min_airflow.sql` | `sql_screening` | `none` |
| `CHW-1` | Low chilled-water ΔT | `chw1` | `chw1_low_dt.sql` | `sql_screening` | `none` |
| `CHW-2` | DP below SP at max pump speed | `chw_2` | `chw2_dp_low.sql` | `sql_screening` | `none` |
| `CHW-3` | Plant supply temp outside deadband | `chw_3` | `chw3_supply_band.sql` | `sql_screening` | `none` |
| `CHW-4` | Flow high at max pump | `chw_4` | `chw4_flow_high.sql` | `sql_screening` | `none` |
| `HP-1` | Discharge cold when heating | `hp_1` | `hp1_discharge_cold.sql` | `sql_screening` | `none` |
| `WX-1` | OA temperature spike | `wx_1` | `wx1_oa_spike.sql` | `sql_screening` | `none` |
| `CW-OPT-1` | Condenser water not optimized vs wet-bulb | `cw_opt_1` | `cw_opt_1.sql` | `sql_screening` | `none` |
| `CW-APR-1` | High CW approach at full tower fan | `cw_apr_1` | `cw_apr_1.sql` | `sql_screening` | `none` |
| `CW-FAN-1` | Excess tower fan energy vs wet-bulb limit | `cw_fan_1` | `cw_fan_1.sql` | `sql_screening` | `none` |
| `TRIM-1` | Duct static trim advisory | `trim_1` | `trim1_duct_static.sql` | `sql_screening` | `none` |
| `TRIM-3` | HWST trim advisory | `trim_3` | `trim3_hwst.sql` | `sql_screening` | `none` |
| `TRIM-4` | CHW plant reset advisory | `trim_4` | `trim4_chw_reset.sql` | `sql_screening` | `none` |
| `SCHED-1` | Excess / wasted unoccupied fan runtime when the zone is already in the comfort band (optimal-start / schedule misconfig signal). Without zone_t, falls back to unoccupied + fan_on (pandas sched1 base). | `sched1` | `sched1_unoccupied_runtime.sql` | `sql_screening` | `alias` |
| `SCHED-247` | Always-on fan or pump runtime | `_sched247` | `sched247_always_on.sql` | `sql_screening` | `none` |
| `CMD-1` | Fan cmd/status mismatch | `cmd_1` | `cmd1_fan_mismatch.sql` | `sql_screening` | `none` |
| `OA-1` | Low OA fraction | `oa_1` | `oa1_low_oa_frac.sql` | `sql_screening` | `none` |
| `DMP-1` | OA damper leakage | `dmp_1` | `dmp1_oa_damper_leak.sql` | `sql_screening` | `none` |
| `VLV-1` | Cooling valve leakage | `vlv_1` | `vlv1_clg_valve_leak.sql` | `sql_screening` | `none` |
| `AVG-ZONE-TEMP` | Average zone temperature per equipment | `—` | `avg_zone_temp.sql` | `sql_screening` | `intentional_non_applicability` |
| `FAN-RUNTIME-HOURS` | Fan running hours where fan_cmd > 5% (normalized 0-1) | `—` | `fan_runtime_hours.sql` | `sql_screening` | `intentional_non_applicability` |
| `FAULT-ELAPSED-HOURS` | Comfort fault sample count → hours | `—` | `fault_elapsed_hours.sql` | `sql_screening` | `intentional_non_applicability` |
| `ZONE-COMFORT-PCT` | Percent of samples in comfort band | `—` | `zone_comfort_pct.sql` | `sql_screening` | `intentional_non_applicability` |
