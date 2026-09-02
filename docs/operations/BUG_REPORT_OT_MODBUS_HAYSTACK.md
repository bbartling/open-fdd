# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-02 (3.3.18 nightly refresh — post docker maintenance)  
**Platform:** Railway hub @ `sha-ca67707` / `3.3.18+ca677075752d`  
**Host:** bensbench (GHCR pull / local react); bosspi arm64 edge @ `sha-ca67707`  
**Remote edge:** bosspi — fieldbus, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS  
**Train:** `ca677075` (#821 + #822 + #823); VERSION **3.3.18**

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.18 nightly refresh (2026-09-02)

| Check | Evidence |
|-------|----------|
| **#821** merged | `002b0563` — 3.3.17 `recreate_bench_fieldbus` before OT gates |
| **#822** merged | `0e5a9b16` — 3.3.18 gate 03 ingest honesty |
| GHCR Publish | **green** on `ca677075` — images `sha-ca67707` |
| Railway backup | `~/openfdd-backups/railway/20260902T120941Z/` |
| Railway hub re-pin | central→mqtt→web `sha-ca67707`; health `3.3.18+ca677075752d` |
| Local container refresh | `openfdd_maint_update_resume.sh react-ot sha-ca67707` (post docker maintenance) |
| bosspi fieldbus re-pin | `sha-ca67707` arm64; MQTTS `reseau.proxy.rlwy.net:44763` |
| Local `run_all` stress | **PASS** — `reports/nightly-ot-bench_20260902T125016Z/` gates **01–16** (`SKIP_PULL=1`, `WEATHER_SOAK_SECS=120`) |
| `run_all` with GHCR pull | **PARTIAL** — `reports/nightly-ot-bench_20260902T123715Z/` gate **00 pull PASS**; gate **01 FAIL** (fieldbus `health=starting` race — harness fix pending merge) |
| Gate 18 volume restore | **PASS** — `reports/nightly-ot-bench_20260902T124850Z/` (ingest_ok reset accepted when volume data preserved) |
| Phase 2 bench hygiene | **CLOSED** — #821 fieldbus refresh, #822 gate 03 honesty |
| **bldg2 Overview** | **DEFERRED** — `OPENFDD_EQUIPMENT_TYPE=zone_other` + UI sign-off |
| Railway F1 pipeline | **PARTIAL** — BUILDING_100 FC1 **PASS** on new pin; DF55/BUILDING_50/AFDD flood **PENDING** |
| BUILDING_100 local vs Railway | **PASS** — FC1 AHU_1 **118.42 h** Railway @ `sha-ca67707`; artifact `reports/railway-f1-spot_20260902T124900Z/` |

## Verdict — 3.3.18 closeout (2026-09-02 early)

| Check | Evidence |
|-------|----------|
| Local `run_all` (harness-only pin) | **PASS** — `reports/nightly-ot-bench_20260902T013750Z/` gates **01–16** on `sha-3e35b2d` images |

## BUILDING_100 — local vs Railway parity (2026-09-02 @ sha-ca67707)

| API | Railway (`sha-ca67707`) |
|-----|-------------------------|
| `POST /api/fdd/run` FC1 AHU_1 | FAULT **118.42 h** |
| `poll_seconds` | 300 |
| Hub health | `edges:1`, `ingest_ok` advancing |

**Artifact:** `reports/railway-f1-spot_20260902T124900Z/` (prior parity `reports/railway-b100-parity_20260901T190000Z/`).

## Dual pipeline

| Pipeline | Status |
|----------|--------|
| **A Cloud** bosspi → Railway | **PASS** — `pi-1`/`bldg2` `has_telemetry:true`; `ingest_ok` advancing after central redeploy |
| **B Local** react bench | **PASS** — full `run_all` @ `sha-ca67707` (`20260902T125016Z`) |

## Patch cycle — Phase 7 + phase2 bench hygiene (2026-09-01 → 2026-09-02)

| Gate / ID | Symptom | Status on tip harness |
|-----------|---------|------------------------|
| **#528** poll_seconds | harness `poll_seconds=300` | **PATCHED 3.3.16** — gate 06 `poll_seconds≈60` on CSV fixture |
| **fieldbus-poll-stale** | `points_polled:0` after long sessions | **PATCHED 3.3.17** — `recreate_bench_fieldbus` |
| **gate03-ingest-counter** | ingest counter unchanged despite live MQTTS | **PATCHED 3.3.18** |
| **playwright-workflows** | `/rules` redirect + auth timing | **PATCHED 3.3.16** — #818 |
| **gate01-fieldbus-starting** | gate 01 FAIL after fieldbus recreate (`health=starting`) | **PATCHED harness** — wait + skip (PR pending) |
| **gate18-ingest-counter** | gate 18 FAIL on ingest_ok reset after central recreate | **PATCHED harness** — skip when volume data preserved (PR pending) |
| **weather-legitimacy** | Chicago Δ>3°F on short soak | **OPEN** tier-C — passed on short soak runs |

**Artifacts:**

| Pin | Artifact | Result |
|-----|----------|--------|
| `sha-ca67707` | `reports/nightly-ot-bench_20260902T125016Z/` | **PASS** gates 01–16 |
| `sha-ca67707` | `reports/nightly-ot-bench_20260902T123715Z/` | gate 00 pull PASS; gate 01 FAIL (pre-harness fix) |
| `sha-3e35b2d` | `reports/nightly-ot-bench_20260902T013750Z/` | **PASS** gates 01–16 (harness on old images) |

## Railway F1 pipeline (separate tier — partial)

| Check | Last evidence |
|-------|---------------|
| Hub health | `3.3.18+ca677075`, `edges:1`, `ingest_ok` advancing |
| **BUILDING_100 FC1** | **PASS** 2026-09-02 @ `sha-ca67707` — 118.42 h |
| DF55 | **PENDING** — `no matching rules` (DF55 not in registry on hub) |
| BUILDING_50 CSV import + FDD | **PENDING** — package not on bench this session |
| AFDD flood | **PENDING** |
| bldg2 Overview | **DEFERRED** |

Local bench `run_all` green does **not** require Railway F1 in the same session.

## Data restore across patch / nightly re-pin (2026-09-01)

**Model:** durability = **same volume**, not a per-message backup file.

| Data class | Where it lives | Survives image re-pin? |
|------------|----------------|------------------------|
| **CSV / package import** | `workspace/data/csv_buildings/` + Parquet | **Yes** — bind-mount |
| **MQTT stream (live OT)** | `openfdd/history/…/part-*.parquet` | **Yes** |
| **`ingest_ok` counter** | Process/runtime | **Resets** on recreate — use MQTTS + Parquet proof |

**Gate 18 PASS:** `reports/nightly-ot-bench_20260902T124850Z/` (harness accepts ingest_ok reset)

Script: `scripts/nightly-ot-bench/18_volume_restore_smoke.sh`

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **bldg2-overview-signoff** | bosspi `OPENFDD_EQUIPMENT_TYPE=zone_other` + fieldbus re-pin done; UI sign-off pending |
| **railway-f1-stress** | DF55/BUILDING_50/AFDD flood pending |
| **weather-legitimacy-chicago** | Tier-C short soak; full `WEATHER_SOAK_SECS=1800` optional |
| **railway-ui-fdd-stale** | `?site=BUILDING_100` scoped FDD UX — use building filter in API |
| **local-parquet-root-split** | `.cache/parquet` vs `openfdd/` on scoped B100 local queries |
| **lake-credential-rotation** | Rotated; session-env only (no git) |
| **deploy-mqtt-acl-mount** | Local `deploy/mqtt/acl` must be a **file** (not directory); `cp services/mqtt/acl.example deploy/mqtt/acl` |

## Railway hub inventory

| Role | Service |
|------|---------|
| central | `openfdd-central-cQ-F` |
| mqtt | `openfdd-mqtt` |
| web | `openfdd-web` → https://openfdd-web-production-af99.up.railway.app |

## Ops notes

1. Backup before every central re-pin.  
2. Re-pin order: central → mqtt → web; bosspi fieldbus.  
3. After mqtt/central redeploy: `railway redeploy -s openfdd-central-cQ-F` if `edges:0` persists.  
4. Bench refresh: `./scripts/openfdd_maint_update_resume.sh react-ot sha-<tip>` (`--skip-maintenance` after operator docker prune).  
5. Full stress **LAST**: `unset SKIP_PULL` for gate 00 pull evidence; `WEATHER_SOAK_SECS=120` on low-RAM.  
6. `OPENFDD_PARQUET_ROOT=/workspace/openfdd` on Railway when `STORAGE_URL=file:///workspace/openfdd`.
