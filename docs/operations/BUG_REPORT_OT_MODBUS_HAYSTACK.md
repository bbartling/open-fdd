# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-01 (3.3.15 closeout — DataFusion 55 + timing gate pre-req done)  
**Platform:** Railway hub @ `sha-3c9f753` / `3.3.15+3c9f75311ae1`  
**Host:** bensbench (GHCR pull / local react); bosspi arm64 edge  
**Remote edge:** bosspi — fieldbus, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS  
**Train:** outstanding_bug_patches — #803/#804/#812/#813/#814 merged; BACnet CI harness #815

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.15 closeout (2026-09-01)

| Check | Evidence |
|-------|----------|
| **#814** merged | `3c9f7531` — DataFusion 55 stack upgrade |
| **#815** merged | `41af8523` — BACnet→MQTT CI mqtt healthcheck + startup ordering |
| GHCR Publish | `sha-3c9f753` images (3.3.15 product); publish for `41af8523` in progress |
| Railway re-pin | central + mqtt + web → `sha-3c9f753`; backup `~/openfdd-backups/railway/20260901T144551Z/` |
| Public `/api/health` | `version: 3.3.15+3c9f75311ae1`, `edges:1`, `ingest_ok` advancing |
| Local smoke (L1–L2) | `01_health_gates` **13/13 pass**; `10_react_spa` **24 pass** (react-ot) |
| Optional BACnet CI | PR #815 `bacnet-mqtt-e2e` **PASS**; tip master workflow pending post-publish |
| **bldg2 Overview** | **DEFERRED** — bosspi fieldbus re-pin + `OPENFDD_EQUIPMENT_TYPE=zone_other` UI sign-off |
| Full `run_all` stress | **IN PROGRESS** — `WEATHER_SOAK_SECS=120` shortened tier on bensbench |

## Verdict — 3.3.14 MQTT Overview parity (2026-08-31)

| Check | Evidence |
|-------|----------|
| **PR #810** merged | `a1b1c521` — MQTT `equipment_type` tags, `equipment_types.json` persist on flush, Overview health shells |
| GHCR Publish | Run `33435756763` **success** — all images `sha-a1b1c52` |
| Railway re-pin | central + mqtt + web → `sha-a1b1c52`; backup `~/openfdd-backups/railway/20260831T204204Z/` |
| Public `/api/health` | `version: 3.3.14+a1b1c5215e8d`, `edges:1`, `ingest_ok` advancing |
| Local smoke (L1–L2) | `01_health_gates` 10/12 pass (fieldbus `:8081` absent — bosspi→Railway only); `10_react_spa` **24 pass** |
| BUILDING_100 regression | Prior **PASS** (3.3.12 stress); not re-run this cycle |
| **bldg2 Overview** | **DEFERRED** — bosspi fieldbus re-pin + `OPENFDD_EQUIPMENT_TYPE=zone_other`; UI sign-off after equip types ingest |

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
| **A Cloud** bosspi → Railway | **PASS** streaming @ 3.3.15 (hub re-pinned) |
| **B Local** react `sha-3c9f753` | **PASS** SPA + health gates |

## This cycle — bugs found / patched

| ID | Severity | Resolution |
|----|----------|------------|
| **#803 lint hygiene** | P2 | **CLOSED** — #812 merged |
| **#804 DataFusion 55** | P1 | **CLOSED** — #814 merged (`3c9f753`) |
| **Patch D parquet root** | P1 | **CLOSED** — #813 merged |
| **Optional BACnet→MQTT CI** | P2 CI | **FIXED** — #815 mqtt healthcheck + smoke ordering |
| **mqtt-equipment-types-missing** | P0 bldg2 Overview | **FIXED 3.3.14** — fieldbus `equipment_type` tag + central `equipment_types.json` persist (#810) |
| **overview-shells-hidden** | P0 MQTT UX | **FIXED 3.3.14** — all health-matrix shells always visible (#810) |
| **csv-flood-vav-parent-equip** | P0 AFDD stream sim | **FIXED** 3.3.12 — `csv_flood_afdd_routine_sim.py` leaf equipment_id |
| **lake-current-ts-column** | P1 bench lake tool | **FIXED** private sidecar — `polled_at` not `ts` |
| **lake-role-heuristics** | P2 packaging | Manual AHU package maps vendor leaf names to cookbook roles |

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **bldg2-overview-signoff** | Hub on `sha-3c9f753`; bosspi needs `OPENFDD_EQUIPMENT_TYPE=zone_other` + fieldbus re-pin → confirm Zone Other + sensor faults in UI |
| **lake-credential-rotation** | Read-only lake password was shared in chat — rotate; session-env only |
| **lake→openfdd packaging** | Manual zip builder worked; formalize in private sidecar later |
| **local-fdd-latency** | **CLOSED** — Patch D (#813) |

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
4. Bench pin: `OPENFDD_IMAGE_TAG=sha-3c9f753` in local `.env` (gitignored).  
5. AFDD stream sim: `scripts/csv_flood_afdd_routine_sim.py` + `scripts/fixtures/b50_afdd_routine.json`.  
6. Private lake bench: read-only Postgres via session tunnel; credentials never in git.
