# BUILDING_100 55-rule DataFusion run

Generated: 2026-07-13 14:10 UTC (gate-injection re-run)

- building: `BUILDING_100`
- source: local private tree (not committed)
- registry: 55 rules
- rules_run: 55
- rules_succeeded (PASS+FAULT row aggregates): 35
- rules_failed (ERROR): 0
- rules_skipped (SKIPPED_MISSING_ROLES): 19
- NOT_APPLICABLE_EQUIPMENT_TYPE (rule-level aggregate): 1 (HP-1)
- total_ms: 35530
- poll_seconds: 300.0

## Six-status distribution (row-level)

- `PASS`: 437
- `FAULT`: 180
- `NOT_APPLICABLE_EQUIPMENT_TYPE`: 1111
- `SKIPPED_MISSING_ROLES`: 19 (rule-level; no per-equipment rows)
- `SKIPPED_EQUIPMENT_OFF`: 0 in this run (active proof present on evaluated AHUs)
- `ERROR`: 0

## Vibe19 numeric parity (proven overlap)

Source: `docs/benchmarks/parity_b100_latest/`

| Metric | Value |
| --- | ---: |
| compared_cells | 1488 |
| exact_status_matches | 1211 |
| status_mismatches | 277 |
| numeric_within_tolerance (0.5h) | 266 |
| numeric_mismatches | 157 |
| max_abs_delta_h | ~2624 (SV-STALE / CHILLER — mapping: enable setpoint as `oa_t`) |
| FC fault_hours within 0.5h | 565 / 576 |
| FC8 AHU_1 | oracle 381.67h / Open-FDD 362.5h (Δ≈19h) |
| SV-STALE AHU_1 | **exact** (180.67h) |
| pass | **false** |

Root causes still open for remaining mismatches:

1. Plant `SV-STALE` false positives when non-sensor setpoints are mapped into sweep roles.
2. `SV-FLATLINE` under-detect vs oracle on some VAVs/plants.
3. Status vocabulary differences (`NOT_APPLICABLE` vs `PASS` on non-applicable equipment rows).
4. Residual FC hour deltas (~0.5–20h) after RUN gate + startup injection.

## Per-rule status

| rule | status | rows | ms |
| --- | --- | ---: | ---: |
| FAN-RUNTIME-HOURS | PASS | 2 | 23 |
| VAV-1 | FAULT | 44 | 266 |
| AVG-ZONE-TEMP | PASS | 44 | 17 |
| ZONE-COMFORT-PCT | PASS | 44 | 22 |
| FAULT-ELAPSED-HOURS | FAULT | 44 | 18 |
| OAT-METEO | FAULT | 2 | 51 |
| FC13-SAT-HIGH | FAULT | 48 | 277 |
| ECON-2 | FAULT | 48 | 285 |
| FC1 | FAULT | 48 | 262 |
| FC2 | FAULT | 48 | 262 |
| FC3 | PASS | 48 | 273 |
| FC7 | PASS | 48 | 247 |
| FC8 | FAULT | 48 | 254 |
| FC9 | FAULT | 48 | 248 |
| FC10 | FAULT | 48 | 260 |
| FC11 | FAULT | 48 | 252 |
| FC12 | FAULT | 48 | 280 |
| ECON-1 | FAULT | 48 | 24 |
| ECON-4 | FAULT | 48 | 264 |
| PID-HUNT-1 | SKIPPED_MISSING_ROLES | 0 | 0 |
| SV-RANGE | FAULT | 48 | 245 |
| SV-FLATLINE | PASS | 48 | 2760 |
| SV-SPIKE | FAULT | 48 | 536 |
| SV-STALE | FAULT | 48 | 2702 |
| SV-4 | FAULT | 48 | 262 |
| FC4 | PASS | 48 | 448 |
| FC5 | PASS | 48 | 260 |
| FC6 | SKIPPED_MISSING_ROLES | 0 | 0 |
| FC14 | SKIPPED_MISSING_ROLES | 0 | 0 |
| FC15 | SKIPPED_MISSING_ROLES | 0 | 0 |
| AHU-SATDEV | FAULT | 48 | 279 |
| AHU-DUCTHI | FAULT | 48 | 259 |
| AHU-SIMUL-HEAT-COOL | PASS | 48 | 265 |
| ECON-3 | PASS | 48 | 294 |
| ECON-5 | SKIPPED_MISSING_ROLES | 0 | 0 |
| OA-1 | FAULT | 48 | 250 |
| DMP-1 | PASS | 48 | 266 |
| VAV-3 | SKIPPED_MISSING_ROLES | 0 | 0 |
| VAV-4 | SKIPPED_MISSING_ROLES | 0 | 0 |
| VAV-5 | SKIPPED_MISSING_ROLES | 0 | 0 |
| VAV-7 | SKIPPED_MISSING_ROLES | 0 | 0 |
| VAV-REHEAT-STUCK | SKIPPED_MISSING_ROLES | 0 | 0 |
| CHW-1 | SKIPPED_MISSING_ROLES | 0 | 0 |
| CHW-2 | SKIPPED_MISSING_ROLES | 0 | 0 |
| CHW-3 | SKIPPED_MISSING_ROLES | 0 | 0 |
| CHW-4 | SKIPPED_MISSING_ROLES | 0 | 0 |
| HP-1 | NOT_APPLICABLE_EQUIPMENT_TYPE | 48 | 283 |
| WX-1 | FAULT | 48 | 296 |
| WX-2 | SKIPPED_MISSING_ROLES | 0 | 0 |
| TRIM-1 | SKIPPED_MISSING_ROLES | 0 | 0 |
| TRIM-3 | SKIPPED_MISSING_ROLES | 0 | 0 |
| TRIM-4 | SKIPPED_MISSING_ROLES | 0 | 0 |
| SCHED-1 | SKIPPED_MISSING_ROLES | 0 | 0 |
| CMD-1 | FAULT | 48 | 258 |
| VLV-1 | FAULT | 48 | 289 |

## Notes

- Weather ingested via synthesized `columns.csv` when export omits it.
- Optional missing roles project as `CAST(NULL AS DOUBLE)` so SV window arithmetic plans.
- `fan_status` comparisons use VARCHAR normalization only (no Float64=Boolean).
- `LEAST`/`GREATEST` replaced with portable CASE expressions where needed.
- This is an **execution** report, not Pandas oracle numeric parity. Oracle compare remains open for #482.
- Skipped rules lack required roles on this building (expected for plant/CHW/PID/sched/WX-2/etc.).
