# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-30 (enhanced CSV/AFDD stress + tip `3.3.12`)  
**Platform:** Railway hub re-pinned to tip after `3.3.12` Publish  
**Host:** bensbench (ops / Railway CLI / local GHCR pull); bosspi arm64 edge  
**Remote edge:** bosspi — fieldbus tip, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS  
**Train:** patch_cycle_3.3.11 closeout + enhanced CSV flood / private-lake bench AFDD

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — enhanced stress (2026-08-30 evening)

| Check | Evidence |
|-------|----------|
| Public `/api/health` | `edges:1`, `ingest_ok` advancing (100+), tip sha on hub |
| MQTT stream (bosspi) | `GET /api/edges` → `pi-1` / `bldg2` `has_telemetry:true` |
| BUILDING_50 CSV import | `POST /api/csv/import/package` **HTTP 200** (`raw_BUILDING_50_openfdd.zip`) |
| BUILDING_50 AFDD flood (12h) | **PASS** after flood-script fix — 11 appends × 48 equip, AFDD every 3 steps `rules_run=5` |
| BUILDING_50 FDD + series | `POST /api/fdd/run` ok; `GET /api/fdd/series?equipment_id=AHU_1&rule_id=FC1` returns rows |
| Private lake bench package | Manual zip from read-only Postgres scrape → import **200**; FDD ok (PASS/FAULT); series **664** rows |
| BUILDING_100 | Prior closeout **PASS** |

## Dual pipeline

| Pipeline | Status |
|----------|--------|
| **A Cloud** bosspi → Railway | **PASS** streaming |
| **B Local** react tip | Hub healthy (prior); not re-tested this evening |

## This cycle — bugs found / patched

| ID | Severity | Resolution |
|----|----------|------------|
| **csv-flood-vav-parent-equip** | P0 for AFDD stream sim | **FIXED** in `scripts/csv_flood_afdd_routine_sim.py` — nested `VAV/<id>/history_wide.csv` used parent `VAV` as `equipment_id` → append failed `equipment VAV missing history_wide.csv`. Use leaf folder (`parts[-2]`). Ships in **3.3.12**. |
| **lake-current-ts-column** | P1 bench lake tool | **FIXED** in private sidecar scrape tool — current snapshot table uses `polled_at`, not `ts`. |
| **lake-role-heuristics** | P2 packaging | Manual AHU package maps vendor leaf names to cookbook roles — 13 roles / 7d / 15‑min grid. |

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **railway-spa-overview-blank** / **mqtt-role_map** | Live MQTT Overview charts may still need hub `role_map.json` for bldg2 (aliases help; full cookbook map preferred) |
| **lake-credential-rotation** | Read-only lake password was shared in chat — rotate and keep session-env only |
| **lake→openfdd packaging** | Manual zip builder worked for bench AHU package; formalize in private sidecar tool later (no Railway write from lake tool by default) |
| **local-fdd-latency** | Full B100 local FDD still soft-OPEN |
| **#803 lint hygiene** | Scoped Rust lint sweep — [issue #803](https://github.com/bbartling/open-fdd/issues/803) |
| **#804 thrift / DF upgrade** | DataFusion 54+ / Arrow 59+ / Parquet 57+ — [issue #804](https://github.com/bbartling/open-fdd/issues/804) (after #803) |
| **Optional BACnet→MQTT CI** | Not a product gate |

## AFDD flood evidence (post-fix)

```
seed: equipment=51 rows=82219
append 1..11: rows_added=576 each (48 equip)
AFDD steps 3,6,9: fdd ok rules_run=5 faults=3 ~1s
artifacts: reports/wattlab-parity/artifacts/csv_flood_sim/BUILDING_50/
```

## Railway hub inventory

| Role | Service |
|------|---------|
| central | `openfdd-central-cQ-F` |
| mqtt | `openfdd-mqtt` |
| web | `openfdd-web` → https://openfdd-web-production-af99.up.railway.app |

## Ops notes

1. Backup before every central re-pin.  
2. Re-pin order: central → mqtt → web; bosspi fieldbus; redeploy central if ingest stuck at 0.  
3. `OPENFDD_PARQUET_ROOT=/workspace/openfdd` when `OPENFDD_STORAGE_URL=file:///workspace/openfdd`.  
4. AFDD stream sim: `scripts/csv_flood_afdd_routine_sim.py` + `scripts/fixtures/b50_afdd_routine.json`.  
5. Private lake bench: read-only Postgres via session tunnel; credentials never in git.
