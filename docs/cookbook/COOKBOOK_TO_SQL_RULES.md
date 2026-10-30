# Cookbook → SQL rule mapping

> **Historical crosswalk.** The row mappings remain useful as an index; status and proof labels predate the SI cutover and are not current parity evidence. Current execution is PostgreSQL/Timescale SQL (`sql/fdd/`) with one canonical telemetry writer and no dual writes.

Cross-reference between the PostgreSQL SQL and pandas expression cookbooks. Current production registry: [`sql/fdd/registry.yaml`](../../sql/fdd/registry.yaml).

Legacy proof labels are not qualification claims. SI qualification requires the frozen IP baseline → pandas IP = pandas SI → pandas SI = SQL SI → live P3 SQL SI = IP baseline chain. Source units are engineer-declared and normalized once; see [unit contract](../modeling/units.md) and [ADR-012](../architecture/adr-012-si-processing-and-qualification.md).

| Cookbook / rule ID | SQL rule_id | SQL file | Required roles | Confirm (s) | Parity | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| VAV-1 / zone comfort | VAV-1 | vav1_comfort_fault.sql | zone_t | 900 | historical label | Tunable ZONE_T_LO/HI and REQUIRE_OCCUPIED (default 1). Unoccupied setback stays VAV-2. |
| OAT-METEO | OAT-METEO | oat_meteo_fault.sql | oa_t | 900 | historical label | Weather-staged wx join |
| FC13 SAT high | FC13-SAT-HIGH | sat_high_fault.sql | sat, sat_sp, clg_valve_pct, oa_damper_pct | 600 | historical label | |
| ECON-2 unfavorable OA | ECON-2 | economizer_fault.sql | oa_t, oa_damper_pct | 300 | historical label | Registry confirm aligned to cookbook |
| FC1 duct static | FC1 | fc1_duct_static_low.sql | duct_static, duct_static_sp, fan_cmd | 300 | historical label | |
| FC2 MAT low | FC2 | fc2_mat_low.sql | mat, oa_t, rat, fan_cmd | 600 | historical label | |
| FC3 MAT high | FC3 | fc3_mat_high.sql | mat, oa_t, rat, fan_cmd | 600 | historical label | |
| FC7 SAT low heat | FC7 | fc7_sat_low_heating.sql | sat, sat_sp, htg_valve_pct, fan_cmd | 600 | historical label | Missing htg_valve_pct on some AHUs |
| FC8 SAT/MAT econ | FC8 | fc8_sat_mat_econ.sql | sat, mat, oa_damper_pct, clg_valve_pct | 600 | historical label | |
| FC9 OAT vs SAT SP | FC9 | fc9_oa_sat_sp_econ.sql | oa_t, sat_sp, oa_damper_pct, clg_valve_pct | 600 | historical label | |
| FC10 MAT-OAT | FC10 | fc10_mat_oa_clg.sql | mat, oa_t, oa_damper_pct, clg_valve_pct | 600 | historical label | |
| FC11 OAT low / SAT SP | FC11 | fc11_oa_sat_sp_clg.sql | oa_t, sat_sp, oa_damper_pct, clg_valve_pct | 600 | historical label | |
| FC12 SAT vs MAT | FC12 | fc12_sat_mat_clg.sql | sat, mat, oa_damper_pct, clg_valve_pct | 600 | historical label | |
| ECON-1 stuck closed | ECON-1 | econ1_stuck_closed.sql | fan_cmd, oa_damper_pct, oa_t | 600 | historical label | |
| ECON-4 low OA frac | ECON-4 | econ4_low_oa_frac.sql | mat, rat, oa_t, fan_cmd | 600 | historical label | |
| ECON-5 preheat | ECON-5 | — | preheat_leave_t, htg_valve_pct | — | historical label | No SQL file yet; missing columns |
| FAN runtime | FAN-RUNTIME-HOURS | fan_runtime_hours.sql | fan_cmd | 0 | historical label | Analytics rollup |
| Avg zone temp | AVG-ZONE-TEMP | avg_zone_temp.sql | zone_t | 0 | historical label | |
| Zone comfort % | ZONE-COMFORT-PCT | zone_comfort_pct.sql | zone_t | 0 | historical label | |
| Fault elapsed | FAULT-ELAPSED-HOURS | fault_elapsed_hours.sql | zone_t | 0 | historical label | |

SI (`metric-c-v2`) is canonical for storage and processing; the PostgreSQL cookbook is an engineering expression catalog, and pandas is an offline oracle. This cross-reference does not certify parity. The qualification sequence is frozen IP baseline, pandas IP = pandas SI, pandas SI = SQL SI, and live P3 SQL SI = IP baseline.


**Python oracle:** optional — `tools/python_oracle/export_pandas_oracle.py` (requires full cookbook stack; not production runtime).

**Tuning:** see [SQL rule tuning contract](../migration/vibe19/SQL_RULE_TUNING_CONTRACT.md).
