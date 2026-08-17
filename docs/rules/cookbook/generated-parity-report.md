---
title: Generated parity report
parent: Rule Cookbook
nav_order: 7
---

# Generated parity report

Auto-generated from `sql_rules/generated/parity_inventory.yaml`.
Do not edit by hand. Run `python3 scripts/generate_cookbook_report.py`.

62 is the executable pandas cookbook (CookbookRule constructors). 66 is the SQL registry: those 62 twins plus 4 SQL-only analytics. Aliases SV-SLEW, FC13, and excess_runtime are not extra rules.

- Pandas diagnostics: **62**
- SQL analytics: **4**
- SQL registry: **66**
- Building 100 cartesian: 48 equipment × 62 diagnostics

## Difference classes

| Class | Count |
| --- | ---: |
| `alias` | 2 |
| `intentional_non_applicability` | 4 |
| `missing_implementation` | 1 |
| `none` | 58 |
| `semantic_gap` | 1 |

## Matrix

| rule_id | title | pandas | SQL | parity | class |
| --- | --- | --- | --- | --- | --- |
| `SV-RANGE` | Sensor out of hard range | `_sweep_range` | `sv_range.sql` | `sql_screening` | `none` |
| `SV-FLATLINE` | Sensor flatline (stuck) | `_sweep_flatline` | `sv_flatline.sql` | `sql_screening` | `none` |
| `SV-SPIKE` | Sensor rate-of-change spike | `_sweep_spike` | `sv_spike.sql` | `sql_screening` | `none` |
| `SV-STALE` | Stale data (no fresh samples) | `_sweep_stale` | `sv_stale.sql` | `sql_screening` | `none` |
| `SV-RATE` | Context-aware sensor rate of change | `_sv_rate_compute` | `sv_rate.sql` | `sql_screening` | `semantic_gap` |
| `PID-HUNT-1` | Suspected control-output hunting | `_pid_hunt_1` | `pid_hunt_1.sql` | `sql_screening` | `none` |
| `FC1` | Duct static below SP at full fan (GL36 A) | `fc1` | `fc1_duct_static_low.sql` | `sql_screening` | `none` |
| `FC2` | MAT below OAT/RAT envelope (GL36 B) | `fc2` | `fc2_mat_low.sql` | `sql_screening` | `none` |
| `FC3` | MAT above OAT/RAT envelope (GL36 C) | `fc3` | `fc3_mat_high.sql` | `sql_screening` | `none` |
| `FC4` | PID hunting (operating-state oscillation) | `fc4` | `fc4_os_hunting.sql` | `sql_screening` | `none` |
| `FC5` | SAT cold when heating commanded (GL36 D) | `fc5` | `fc5_sat_cold_heating.sql` | `sql_screening` | `none` |
| `FC6` | Estimated OA fraction mismatch | `fc6` | `fc6_oa_frac_mismatch.sql` | `sql_screening` | `none` |
| `FC7` | SAT low with full heating (GL36 E) | `fc7` | `fc7_sat_low_heating.sql` | `sql_screening` | `missing_implementation` |
| `FC8` | SAT/MAT mismatch in economizer (GL36 F) | `fc8` | `fc8_sat_mat_econ.sql` | `sql_screening` | `none` |
| `FC9` | OAT too warm for free cooling (GL36 G) | `fc9` | `fc9_oa_sat_sp_econ.sql` | `sql_screening` | `none` |
| `FC10` | OAT/MAT mismatch + mech cooling (GL36 H) | `fc10` | `fc10_mat_oa_clg.sql` | `sql_screening` | `none` |
| `FC11` | OAT/MAT mismatch economizer-only (GL36 I) | `fc11` | `fc11_oa_sat_sp_clg.sql` | `sql_screening` | `none` |
| `FC12` | SAT above blend in cooling (GL36 J) | `fc12` | `fc12_sat_mat_clg.sql` | `sql_screening` | `none` |
| `FC13` | SAT above SP at full cooling (GL36 K) | `fc13` | `sat_high_fault.sql` | `sql_screening` | `alias` |
| `FC14` | CHW coil ΔT when inactive (GL36 L) | `fc14` | `fc14_chw_coil_dt_inactive.sql` | `sql_screening` | `none` |
| `FC15` | HW coil ΔT when inactive (GL36 M) | `fc15` | `fc15_hw_coil_dt_inactive.sql` | `sql_screening` | `none` |
| `AHU-SATDEV` | SAT deviation from setpoint | `ahu_sat_dev` | `ahu_satdev.sql` | `sql_screening` | `none` |
| `AHU-DUCTHI` | Duct static pressure high | `ahu_duct_high` | `ahu_ducthi.sql` | `sql_screening` | `none` |
| `AHU-SIMUL` | Heating and cooling simultaneous | `ahu_simul_heat_cool` | `ahu_simul.sql` | `sql_screening` | `none` |
| `OAT-METEO` | BAS outdoor-air sensor vs Open-Meteo | `oat_vs_meteo` | `oat_meteo_fault.sql` | `sql_screening` | `none` |
| `ECON-1` | Economizer stuck closed | `econ1` | `econ1_stuck_closed.sql` | `sql_screening` | `none` |
| `ECON-2` | Economizing when outdoor unfavorable | `econ2` | `economizer_fault.sql` | `sql_screening` | `none` |
| `ECON-3` | Mech cooling without integrated economizer | `econ2` | `econ3_mech_without_econ.sql` | `sql_screening` | `none` |
| `ECON-4` | Low estimated OA fraction | `econ4` | `econ4_low_oa_frac.sql` | `sql_screening` | `none` |
| `ECON-5` | Preheat over-conditioning | `econ5` | `econ5_preheat_over.sql` | `sql_screening` | `none` |
| `ECON-6` | Economizing in freezing weather | `econ6_compute` | `econ6_econ_freezing.sql` | `sql_screening` | `none` |
| `ECON-7` | Economizer OK but not economizing | `econ7_compute` | `econ7_ok_not_economizing.sql` | `sql_screening` | `none` |
| `MECH-OAT-1` | Mechanical cooling below 60°F web OAT | `mech_oat1_compute` | `mech_oat_1.sql` | `sql_screening` | `none` |
| `CHW-NOLOAD-1` | Chiller running with no building load | `chw_noload1_compute` | `chw_noload_1.sql` | `sql_screening` | `none` |
| `VAV-1` | Zone comfort band | `vav1` | `vav1_comfort_fault.sql` | `sql_screening` | `none` |
| `VAV-2` | Night setback miss | `vav2` | `vav2_night_setback.sql` | `sql_screening` | `none` |
| `VAV-3` | Excessive reheat during warm weather | `vav3` | `vav3_excessive_reheat.sql` | `sql_screening` | `none` |
| `VAV-4` | Damper stuck at full open | `vav4` | `vav4_damper_full_open.sql` | `sql_screening` | `none` |
| `VAV-5` | Airflow sensor bias | `vav5` | `vav5_airflow_bias.sql` | `sql_screening` | `none` |
| `VAV-6` | Reheat when cooling available | `vav6` | `vav6_reheat_free_cool.sql` | `sql_screening` | `none` |
| `VAV-REHEAT` | Reheat valve stuck / no temp rise | `vav_reheat_stuck` | `vav_reheat.sql` | `sql_screening` | `none` |
| `VAV-AHU-LEAVE` | VAV leave vs parent AHU SAT (fedBy) | `vav_vs_ahu_leave` | `vav_ahu_leave.sql` | `sql_screening` | `none` |
| `VAV-7` | Min airflow / fixed high flow | `vav7` | `vav7_min_airflow.sql` | `sql_screening` | `none` |
| `CHW-1` | Low chilled-water ΔT | `chw1` | `chw1_low_dt.sql` | `sql_screening` | `none` |
| `CHW-2` | DP below SP at max pump speed | `chw2` | `chw2_dp_low.sql` | `sql_screening` | `none` |
| `CHW-3` | Plant supply temp outside deadband | `chw3` | `chw3_supply_band.sql` | `sql_screening` | `none` |
| `CHW-4` | Flow high at max pump | `chw4` | `chw4_flow_high.sql` | `sql_screening` | `none` |
| `HP-1` | Discharge cold when heating | `hp1` | `hp1_discharge_cold.sql` | `sql_screening` | `none` |
| `WX-1` | OA temperature spike | `wx1` | `wx1_oa_spike.sql` | `sql_screening` | `none` |
| `CW-OPT-1` | Condenser water not optimized vs wet-bulb | `cw_opt` | `cw_opt_1.sql` | `sql_screening` | `none` |
| `CW-APR-1` | High CW approach at full tower fan | `cw_apr` | `cw_apr_1.sql` | `sql_screening` | `none` |
| `CW-FAN-1` | Excess tower fan energy vs wet-bulb limit | `cw_fan_excess` | `cw_fan_1.sql` | `sql_screening` | `none` |
| `TRIM-1` | Duct static trim advisory | `trim1` | `trim1_duct_static.sql` | `sql_screening` | `none` |
| `TRIM-3` | HWST trim advisory | `trim3` | `trim3_hwst.sql` | `sql_screening` | `none` |
| `TRIM-4` | CHW plant reset advisory | `trim4` | `trim4_chw_reset.sql` | `sql_screening` | `none` |
| `SCHED-1` | Unoccupied runtime | `sched1` | `sched1_unoccupied_runtime.sql` | `sql_screening` | `alias` |
| `SCHED-247` | Always-on fan or pump runtime | `_sched247` | `sched247_always_on.sql` | `sql_screening` | `none` |
| `RESET-1` | SAT reset not tracking outdoor air | `reset1` | `reset1_sat_oa_reset.sql` | `sql_screening` | `none` |
| `CMD-1` | Fan cmd/status mismatch | `cmd1` | `cmd1_fan_mismatch.sql` | `sql_screening` | `none` |
| `OA-1` | Low OA fraction | `oa1` | `oa1_low_oa_frac.sql` | `sql_screening` | `none` |
| `DMP-1` | OA damper leakage | `dmp1` | `dmp1_oa_damper_leak.sql` | `sql_screening` | `none` |
| `VLV-1` | Cooling valve leakage | `vlv1` | `vlv1_clg_valve_leak.sql` | `sql_screening` | `none` |
| `AVG-ZONE-TEMP` | Average zone temperature per equipment | `—` | `avg_zone_temp.sql` | `sql_screening` | `intentional_non_applicability` |
| `FAN-RUNTIME-HOURS` | Fan running hours where fan_cmd > 5% (normalized 0-1) | `—` | `fan_runtime_hours.sql` | `sql_screening` | `intentional_non_applicability` |
| `FAULT-ELAPSED-HOURS` | Comfort fault sample count → hours | `—` | `fault_elapsed_hours.sql` | `sql_screening` | `intentional_non_applicability` |
| `ZONE-COMFORT-PCT` | Percent of samples in comfort band | `—` | `zone_comfort_pct.sql` | `sql_screening` | `intentional_non_applicability` |
