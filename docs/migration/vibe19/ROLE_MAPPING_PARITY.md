# Role mapping parity — Python vs Rust

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

Aligns `open_fdd.role_candidates.ROLE_CANDIDATES` / `haystack_point_to_role()` with `fdd_core::normalize_role`, `normalize_haystack_slug`, and `load_column_role_map`.

## NF tag normalization (#1405)

Before the explicit Haystack slug table, `normalize_haystack_slug` applies framework-wide rules (every site):

| Rule | Example in | Example out |
| --- | --- | --- |
| `-temperature` → `-temp` | `discharge-air-temperature-setpoint-active` | …`-temp`… |
| `-setpoint` → `-sp` | `zone-air-temp-setpoint` | `zone-air-temp-sp` |
| Drop trailing `-active` when tag contains `-sp` | `duct-static-pressure-setpoint-active` | `duct-static-pressure-sp` |
| Leading `hw-` → `hot-water-` | `hw-supply-temp` | `hot-water-supply-temp` |
| Leading `chw-` → `chilled-water-` | `chw-st` | `chilled-water-st` |
| Drop trailing `-local` | `return-air-humidity-local` | `return-air-humidity` |

New explicit slugs: `zone-airflow-sp` → `zone_airflow_sp`, `return-air-humidity` → `ra_h`.

Golden snapshot: `crates/fdd_core/testdata/haystack_point_role_golden.json` (Rust + PyPI parity tests).

## Python source of truth

- `open_fdd/role_candidates.py` — `ROLE_CANDIDATES`, `normalize_haystack_slug`, `haystack_point_to_role`
- Historical: `fdd_app/backend/cookbook_engine.py` — retired Streamlit oracle
- `fdd_app/backend/economizer_point_mapping.json` — AHU column aliases
- `fdd_app/sidecar/historian_export.py` — pivot export roles

## Rust implementation

- `crates/fdd_core/src/columns.rs` — `normalize_haystack_slug`, `haystack_point_to_role`, `normalize_role`, `infer_role_from_column_name`, `load_column_role_map`
- Applied at Parquet ingest (`fdd_store/ingest.rs`) — first column wins per logical role

## Role candidate table (P0)

| Logical role | Python RDF candidates | Rust aliases added (Stage 2) | BUILDING_100 |
| --- | --- | --- | --- |
| fan_cmd | fan_cmd, supply_fan | supply_fan_speed_pct, fan_speed | AHU_1/2 via supply_fan |
| fan_status | fan_status | fan_proof, supply_fan_status | Present (separate from fan_cmd) |
| zone_t | zone_temp, space_temp | zone_temp, spacetemp heuristics | VAV boxes |
| oa_t | oat, oa_t, weather_oat | outside_air_temp | AHU + weather |
| rat | rat, ra_t | return_air_temp, ra_t | AHU |
| mat | mat | mixed_air_temp, ma_t | AHU |
| sat | sat | discharge_air_temp | AHU |
| sat_sp | sat_sp | dat_reset, **cooling_setpoint**, **effective_setpoint** | Mapped from setpoint columns |
| clg_valve_pct | cooling_cmd | chw_valve, clg_valve | AHU |
| htg_valve_pct | heating_cmd | htg_valve, hw_valve | Partial — not on all AHUs |
| oa_damper_pct | oa_damper_cmd, oa_damper_pos | damper, dmpr | AHU |
| duct_static | (physical) | da_p_inwc | AHU |
| duct_static_sp | (physical) | da_p_setpoint | **Missing** on BUILDING_100 |
| chw_supply_t | chws | chws_t, chwst | CHILLER_* |
| chw_return_t | chwr | chwr_t, chwrt | CHILLER_* |
| occ_mode | occ_mode | occupancy, schedule | Limited |

## Gaps found and fixes (Stage 2)

| Gap | Fix | Impact |
| --- | --- | --- |
| `fan_status` mapped to `fan_cmd` | Separate `fan_status` role | Fan proof vs speed |
| `return_fan` stole fan_cmd slot | `return_fan` → own role (ignored by SQL) | Correct supply fan ingest |
| `cooling_setpoint` not → sat_sp | Map to `sat_sp` | FC7/9/11/FC13 SQL can run |
| `ra_t` alias | Map to `rat` | FC2/FC3 |
| Utf8View equipment_id in SQL JSON | `StringViewArray` in format_cell | Compare keys match |

## Unresolved roles (BUILDING_100)

| Role | Blocks |
| --- | --- |
| duct_static_sp | FC1 |
| htg_valve_pct (some AHUs) | FC7 |
| preheat_leave_t | ECON-5 |
| wx_oa_t (SQL side) | OAT-METEO true parity |
| occ_mode / schedule | MOTOR-EXCESS, SCHED-1 |

## SQL rule impact

Rules requiring missing roles are skipped in compare (`skipped_missing_roles`). FC1 SQL fails schema check until `duct_static_sp` ingested.

## Next steps

1. Port economizer_point_mapping.json lookups into Rust ingest (layer 2 parity with Python)
2. Weather Parquet sidecar with `wx_oa_t` for OAT-METEO SQL
3. Confirm-window SQL (streak >= N rows) to match `confirm_fault`
