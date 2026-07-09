# Pandas → SQL rule migration

Tracking table for deterministic Open-FDD-style rules. **Python `cookbook_rules.py` remains oracle** until parity column shows ✅.

## Summary

| Status | Count |
| --- | ---: |
| Python cookbook rules | 50 |
| SQL rules in `sql_rules/` | 8 |
| SQL good-fit (P0 threshold/rollup) remaining | ~25 |
| Keep in Python (ML / complex state) | ~12 |
| Sensor sweeps (dynamic columns) | 5 |

## Ported to SQL (stage 1)

| Rule ID | SQL file | Required roles | Output | Parity status |
| --- | --- | --- | --- | --- |
| FAN-RUNTIME-HOURS | `fan_runtime_hours.sql` | `fan_cmd` | `fan_runtime_hours`, `total_hours` | Fixture ✅ · BUILDING_100 ⏳ |
| VAV-1 | `vav1_comfort_fault.sql` | `zone_t` | `fault_hours`, `fault_pct` | Fixture ✅ · BUILDING_100 ⏳ |
| AVG-ZONE-TEMP | `avg_zone_temp.sql` | `zone_t` | avg/min/max zone temp | Fixture ✅ |
| ZONE-COMFORT-PCT | `zone_comfort_pct.sql` | `zone_t` | `comfort_pct` | Fixture ✅ |
| FAULT-ELAPSED-HOURS | `fault_elapsed_hours.sql` | `zone_t` | `fault_samples`, `fault_hours` | Fixture ✅ (proxy mask) |
| OAT-METEO | `oat_meteo_fault.sql` | `oa_t` | `fault_hours`, `fault_pct` | Needs full AHU+weather data |
| FC13-SAT-HIGH | `sat_high_fault.sql` | `sat`, `sat_sp`, `clg_valve_pct` | `fault_hours` | Needs AHU SAT points |
| ECON-2 | `economizer_fault.sql` | `oa_t`, `oa_damper_pct` | `fault_hours` | Needs economizer points |

## P0 — good SQL fit (next PR)

| Rule ID | Python fn | Why SQL fits | Blocker |
| --- | --- | --- | --- |
| FC1 | `fc1` | Threshold + fan gate | Role map for `duct_static` |
| FC2–FC3 | `fc2`, `fc3` | MAT envelope vs OAT/RAT | — |
| FC7–FC13 | `fc7`…`fc13` | SAT/RAT threshold faults | Confirm seconds in SQL window |
| ECON-1,3–5 | `econ_*` | OAT/damper thresholds | Weather join |
| CHW-* | chiller rules | Supply/return temp thresholds | Plant equipment roles |
| MOTOR-EXCESS | motor rollups | `fan_cmd` + occupancy | `occ_mode` schedule data |
| SCHED-1 | schedule compare | Boolean schedule vs fan | Schedule column availability |

## P1 — SQL with windows

| Rule ID | Why harder | Keep in Python until |
| --- | --- | --- |
| SV-FLATLINE | Rolling unchanged window | DataFusion window frames + per-sensor pivot |
| FC4 | Mode-change counting per hour | Stateful mode machine |
| FC15 | Trim response | Needs VAV aggregate sums |

## P2 — keep in Python

| Area | Reason |
| --- | --- |
| SV-RANGE / SV-SPIKE / SV-STALE sweeps | Dynamic per-column sensor iteration |
| ML plugins (`ml_oat_residual`, etc.) | sklearn / custom models |
| Chart downsampling | UI concern, not rule engine |
| `confirm_fault` edge cases | Port after raw SQL masks match |

## SQL conventions

- Table: `history` (unified Parquet glob)
- Poll interval: `300.0` seconds in SQL literals today — **must** parameterize from manifest `effective_poll_seconds` (known limitation)
- Use CTEs; comment rule ID and units at top of each `.sql` file
- Registry: `sql_rules/registry.yaml` — source of truth for `fdd_cli run-rules`

## Parity procedure

1. Run pandas: `cookbook_engine` equipment view → export fault hours JSON.
2. Run Rust: `fdd_cli run-rules` → `.cache/rule_results/<RULE_ID>.json`.
3. Compare: `fdd_cli compare --python-results oracle.json --sql-results sql.json --tolerance 0.5`.
4. Document mismatches in `benchmarks/RUST_DATAFUSION_PARITY_BENCHMARK.md`.
