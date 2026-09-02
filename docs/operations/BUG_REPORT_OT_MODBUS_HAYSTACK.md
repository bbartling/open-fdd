# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-02 (3.3.18 closeout — phase2 bench hygiene + full `run_all` PASS)  
**Platform:** Railway hub @ `sha-3e35b2d` / `3.3.16+3e35b2d45810` (re-pin to `sha-0e5a9b1` after GHCR #822 publish)  
**Host:** bensbench (GHCR pull / local react); bosspi arm64 edge  
**Remote edge:** bosspi — fieldbus, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS  
**Train:** #821/#822 merged on master (`0e5a9b16`); VERSION **3.3.18**

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.18 closeout (2026-09-02)

| Check | Evidence |
|-------|----------|
| **#821** merged | `002b0563` — 3.3.17 `recreate_bench_fieldbus` before OT gates (`fieldbus-poll-stale`) |
| **#822** merged | `0e5a9b16` — 3.3.18 gate 03 ingest honesty (MQTTS + `ingest_ok>0` when counter stale) |
| GHCR Publish | **in progress** on tip `0e5a9b16` — prior pin `sha-3e35b2d` / `3.3.16` still running locally |
| Local container refresh | `openfdd_maint_update_resume.sh react-ot sha-3e35b2d` — fieldbus/mqtt/web recreated |
| Local `run_all` stress | **PASS** — `reports/nightly-ot-bench_20260902T013750Z/` gates **01–16** (`SKIP_PULL=1`, `WEATHER_SOAK_SECS=120`) |
| Phase 2 bench hygiene | **CLOSED** — stress-driven harness fixes (#821 fieldbus refresh, #822 gate 03 honesty) |
| **bldg2 Overview** | **DEFERRED** — bosspi fieldbus re-pin + `OPENFDD_EQUIPMENT_TYPE=zone_other` UI sign-off |
| Railway F1 pipeline | **PARTIAL** — BUILDING_100 FC1/runtime **PASS**; DF55/BUILDING_50/AFDD flood still pending |
| BUILDING_100 local vs Railway | **PASS** — FC1 AHU_1 **118.42 h** both sides; artifact `reports/railway-b100-parity_20260901T190000Z/` |

## Verdict — 3.3.16 closeout (2026-09-01 evening)

| Check | Evidence |
|-------|----------|
| **#817–#820** merged | Phase 7 product + gate 16 e2e + docs closeout |
| Product pin | `sha-3e35b2d` / `3.3.16+3e35b2d45810` |
| Local `run_all` | `215607Z` gates 01–15 PASS; gate 16 green after #818 |

## BUILDING_100 — local vs Railway parity (2026-09-01)

**Question:** Railway UI showed no FC1 faults for AHU_1; run times looked wrong.  
**Answer:** Central API parity is **identical** on pin `sha-3c9f753` when `building_id=BUILDING_100`.

| API | Local | Railway | WattLab dump |
|-----|-------|---------|--------------|
| `POST /api/fdd/run` FC1 AHU_1 | FAULT **118.42 h** | FAULT **118.42 h** | `fdd_findings.csv` **118.42 h** |
| `poll_seconds` | 300 | 300 | — |
| `POST /api/analytics/runtime` AHU_1 `run_hours` | **1638.75** | **1638.75** | — |
| `FAN-RUNTIME-HOURS` AHU_1 | PASS (0 h fault) | PASS (0 h fault) | PASS |
| `GET /api/fdd/series` FC1 AHU_1 | `has_confirmed_fault: true` | same | — |
| `POST /api/analytics/ahu-pressure-health` `duct_low` | true | true | — |

**Artifact:** `reports/railway-b100-parity_20260901T190000Z/` (raw JSON + `summary.json`).

## Dual pipeline

| Pipeline | Status |
|----------|--------|
| **A Cloud** bosspi → Railway | **PASS** streaming @ 3.3.16 hub pin |
| **B Local** react bench | **PASS** full `run_all` @ 3.3.18 harness on `sha-3e35b2d` images |

## Patch cycle — Phase 7 + phase2 bench hygiene (2026-09-01 → 2026-09-02)

| Gate / ID | Symptom | Status on tip harness |
|-----------|---------|------------------------|
| **#528** poll_seconds | harness `poll_seconds=300` | **PATCHED 3.3.16** |
| **fieldbus-poll-stale** | `points_polled:0` after long sessions | **PATCHED 3.3.17** — `recreate_bench_fieldbus` in `00_pull` + `run_all` |
| **gate03-ingest-counter** | ingest counter unchanged after refresh despite live MQTTS | **PATCHED 3.3.18** — accept telemetry + `ingest_ok>0` |
| **playwright-workflows** | `/rules` redirect + auth timing | **PATCHED 3.3.16** — #818 |
| **weather-legitimacy** | Chicago Δ>3°F on short soak | **OPEN** tier-C — passed on `013750Z` run; environmental |

**Artifacts:**

| Pin | Artifact | Result |
|-----|----------|--------|
| `sha-3e35b2d` | `reports/nightly-ot-bench_20260902T013750Z/` | **PASS** gates 01–16 |
| `sha-3e35b2d` | `reports/nightly-ot-bench_20260902T005853Z/` | FAIL gate 03 only (pre-#822) |

## Railway F1 pipeline (separate tier — partial)

| Check | Last evidence |
|-------|---------------|
| Hub health | `3.3.16+3e35b2d`, `ingest_ok` advancing |
| **BUILDING_100 FC1 + runtime** | **PASS** 2026-09-01 |
| DF55 / BUILDING_50 / AFDD flood | **PENDING** |
| bldg2 Overview | **DEFERRED** |

Local bench `run_all` green does **not** require Railway F1 in the same session.

## Data restore across patch / nightly re-pin (2026-09-01)

**Model:** durability = **same volume**, not a per-message backup file.

| Data class | Where it lives | Survives image re-pin? |
|------------|----------------|------------------------|
| **CSV / package import** | `workspace/data/csv_buildings/` + Parquet | **Yes** — bind-mount |
| **MQTT stream (live OT)** | `openfdd/history/…/part-*.parquet` | **Yes** |
| **`ingest_ok` counter** | Process/runtime | May reset on recreate — use MQTTS + Parquet proof |

**Gate 18 PASS:** `reports/volume-restore-smoke_20260901T173000Z/`

Script: `scripts/nightly-ot-bench/18_volume_restore_smoke.sh`

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **bldg2-overview-signoff** | bosspi `OPENFDD_EQUIPMENT_TYPE=zone_other` + fieldbus re-pin |
| **railway-f1-stress** | DF55/BUILDING_50/AFDD flood pending |
| **railway-repin-3.3.18** | Re-pin hub after GHCR `sha-0e5a9b1` publish completes |
| **weather-legitimacy-chicago** | Tier-C short soak; full `WEATHER_SOAK_SECS=1800` optional |

## Railway hub inventory

| Role | Service |
|------|---------|
| central | `openfdd-central-cQ-F` |
| mqtt | `openfdd-mqtt` |
| web | `openfdd-web` → https://openfdd-web-production-af99.up.railway.app |

## Ops notes

1. Backup before every central re-pin.  
2. Re-pin order: central → mqtt → web; bosspi fieldbus.  
3. Bench refresh: `./scripts/openfdd_maint_update_resume.sh react-ot sha-<tip>`  
4. Full stress: `./scripts/nightly-ot-bench/run_all.sh` (auto fieldbus refresh before gates 02/03).  
5. `OPENFDD_PARQUET_ROOT=/workspace/openfdd` on Railway when `STORAGE_URL=file:///workspace/openfdd`.
