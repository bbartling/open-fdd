# Cookbook → SQL rule mapping

Cross-reference between Open-FDD **online expression cookbook** (`docs/rules/cookbook/`) and the **shipped DataFusion SQL registry** (`sql_rules/registry.yaml`).

Proven on BUILDING_100 @ 0.5h tolerance (see `docs/benchmarks/RUST_DATAFUSION_PARITY_BENCHMARK.md`).

| Cookbook / rule ID | SQL rule_id | SQL file | Required roles | Confirm (s) | Parity | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| VAV-1 / zone comfort | VAV-1 | vav1_comfort_fault.sql | zone_t | 900 | proven | Tunable ZONE_T_LO/HI |
| OAT-METEO | OAT-METEO | oat_meteo_fault.sql | oa_t | 900 | proven | Weather-staged wx join |
| FC13 SAT high | FC13-SAT-HIGH | sat_high_fault.sql | sat, sat_sp, clg_valve_pct, oa_damper_pct | 600 | proven | |
| ECON-2 unfavorable OA | ECON-2 | economizer_fault.sql | oa_t, oa_damper_pct | 300 | proven | Registry confirm aligned to cookbook |
| FC1 duct static | FC1 | fc1_duct_static_low.sql | duct_static, duct_static_sp, fan_cmd | 300 | proven | |
| FC2 MAT low | FC2 | fc2_mat_low.sql | mat, oa_t, rat, fan_cmd | 600 | proven | |
| FC3 MAT high | FC3 | fc3_mat_high.sql | mat, oa_t, rat, fan_cmd | 600 | proven | |
| FC7 SAT low heat | FC7 | fc7_sat_low_heating.sql | sat, sat_sp, htg_valve_pct, fan_cmd | 600 | skip | Missing htg_valve_pct on some AHUs |
| FC8 SAT/MAT econ | FC8 | fc8_sat_mat_econ.sql | sat, mat, oa_damper_pct, clg_valve_pct | 600 | proven | |
| FC9 OAT vs SAT SP | FC9 | fc9_oa_sat_sp_econ.sql | oa_t, sat_sp, oa_damper_pct, clg_valve_pct | 600 | proven | |
| FC10 MAT-OAT | FC10 | fc10_mat_oa_clg.sql | mat, oa_t, oa_damper_pct, clg_valve_pct | 600 | proven | |
| FC11 OAT low / SAT SP | FC11 | fc11_oa_sat_sp_clg.sql | oa_t, sat_sp, oa_damper_pct, clg_valve_pct | 600 | proven | |
| FC12 SAT vs MAT | FC12 | fc12_sat_mat_clg.sql | sat, mat, oa_damper_pct, clg_valve_pct | 600 | proven | |
| ECON-1 stuck closed | ECON-1 | econ1_stuck_closed.sql | fan_cmd, oa_damper_pct, oa_t | 600 | proven | |
| ECON-4 low OA frac | ECON-4 | econ4_low_oa_frac.sql | mat, rat, oa_t, fan_cmd | 600 | proven | |
| ECON-5 preheat | ECON-5 | — | preheat_leave_t, htg_valve_pct | — | skip | No SQL file yet; missing columns |
| FAN runtime | FAN-RUNTIME-HOURS | fan_runtime_hours.sql | fan_cmd | 0 | proven | Analytics rollup |
| Avg zone temp | AVG-ZONE-TEMP | avg_zone_temp.sql | zone_t | 0 | proven | |
| Zone comfort % | ZONE-COMFORT-PCT | zone_comfort_pct.sql | zone_t | 0 | proven | |
| Fault elapsed | FAULT-ELAPSED-HOURS | fault_elapsed_hours.sql | zone_t | 0 | proven | |

**Python oracle:** optional — `tools/python_oracle/export_pandas_oracle.py` (requires full cookbook stack; not production runtime).

**Tuning:** see `docs/SQL_RULE_TUNING_CONTRACT.md`.
