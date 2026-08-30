# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-08-30 (enhanced CSV/AFDD/TADCO stress + tip `3.3.12`)  
**Platform:** Railway hub **`3.3.11+752918bedc29`** → re-pin to tip after `3.3.12` Publish  
**Host:** bensbench (ops / Railway CLI / local GHCR pull); bosspi arm64 edge  
**Remote edge:** bosspi — fieldbus tip, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS  
**Train:** patch_cycle_3.3.11 closeout + enhanced CSV flood / TADCO lake AFDD

Private OT LAN addresses, Niagara creds, and TADCO `ben_ro` password live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — enhanced stress (2026-08-30 evening)

| Check | Evidence |
|-------|----------|
| Public `/api/health` | `edges:1`, `ingest_ok` advancing (100+), tip sha on hub |
| MQTT stream (bosspi) | `GET /api/edges` → `pi-1` / `bldg2` `has_telemetry:true` |
| BUILDING_50 CSV import | `POST /api/csv/import/package` **HTTP 200** (`raw_BUILDING_50_openfdd.zip`) |
| BUILDING_50 AFDD flood (12h) | **PASS** after flood-script fix — 11 appends × 48 equip, AFDD every 3 steps `rules_run=5` |
| BUILDING_50 FDD + series | `POST /api/fdd/run` ok; `GET /api/fdd/series?equipment_id=AHU_1&rule_id=FC1` returns rows |
| LibertyCenter (TADCO lake) | Cloudflare tunnel live; package zip import **200**; FDD ok (PASS/FAULT); series **664** rows |
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
| **tadco-niagara-current-ts** | P1 lake tool | **FIXED** in `tadco/tadco_lake_tool.py` (+ scrape / agent prompt) — `niagara_current` has `polled_at`, not `ts`. |
| **tadco-role-heuristics** | P2 packaging | Liberty AHU package now maps Niagara `$20`/`$2d` leaf names (`AHU1 DA-T`→`sat`, etc.) — 13 roles / 7d / 15‑min grid. |

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **railway-spa-overview-blank** / **mqtt-role_map** | Live MQTT Overview charts may still need hub `role_map.json` for bldg2 (aliases help; full cookbook map preferred) |
| **tadco-password-rotation** | Password was shared in Discord/chat — **rotate `ben_ro`** and keep session-env only |
| **tadco→openfdd packaging** | Manual zip builder worked for `LibertyCenter`/`AHU_1`; formalize in `tadco_lake_tool` later (no Railway write from lake tool by default) |
| **local-fdd-latency** | Full B100 local FDD still soft-OPEN |
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
5. TADCO: `cloudflared access tcp` → `127.0.0.1:6543`; `ben_ro` read-only; prefer `niagara_polled_history`.  
