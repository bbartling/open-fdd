# Stage 3/4 merge status report

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Date:** 2026-07-09  
**Canonical branch:** `develop` (GitHub default; `origin/HEAD` → `develop`)  
**Latest commit:** see `git log -1 develop`

## What works (proven @ 0.5h tolerance)

| area | status |
| --- | --- |
| Rust validate + ingest + Parquet cache | ✅ 48 equipment, ~1.5M rows |
| SQL rule batch | ✅ 19/19 rules execute |
| **Full BUILDING_100 parity** | ✅ **368 pass / 0 fail / 11 skipped** |
| Zone analytics | ✅ AVG-ZONE-TEMP, ZONE-COMFORT-PCT, FAULT-ELAPSED-HOURS, VAV-1 |
| All AHU FC/ECON rules (except skips) | ✅ FC1–FC13, ECON-1/2/4, OAT-METEO |
| SQL tuning API + static panel | ✅ `/api/sql-rules*`, `dashboard_sql_tuning.js` |
| Python oracle + dashboard | ✅ Pandas paths retained |

## Valid skips (not bugs)

| rule | reason |
| --- | --- |
| FC7 / ECON-5 | missing `htg_valve_pct` / `preheat_leave_t` on BUILDING_100 AHUs |
| FAN-RUNTIME | plant equipment without fan_cmd |
| VAV_25A | missing zone_t |

## Remaining work (post-parity)

- Per-request Rust SQL preview with session tuning overrides
- `parameters:` blocks for all 19 rules in registry
- React/TypeScript frontend (planned, not started)
- Delete pandas paths only after dashboard wired to SQL preview per rule
