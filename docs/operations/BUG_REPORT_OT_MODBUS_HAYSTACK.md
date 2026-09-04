# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-03 (3.3.20 VERSION bump — x86 field → Railway hub)  
**Platform:** Railway hub + bensbench **x86 fieldbus only** (no Raspberry Pi in stress)  
**Last closed utilities train:** tip `d83dbf91` / `sha-0c1029d` / `3.3.19+0c1029da60c7`  
**This cycle pin:** *fill after GHCR* `sha-<7>` / `3.3.20+…`  
**Field:** bensbench x86 `openfdd-fieldbus` → Railway MQTTS (`bldg2`; MQTT client id currently reused `pi-1` kit — Railway mqtt volume has CA cert but no CA key, so a newly minted `bensbench-1` kit will not verify)  
**Pis freed (not in stress):** bosspi · BensFakeAhu (fake AHU) · Zone1VAV (fake VAV) — vibe13 / other. Private OT LAN addresses stay in session env only.

## Next patch cycle (copy into `.cursor/plans/patch_cycle_3.3.N_<slug>.plan.md`)

Template + commands: [`PATCH_CYCLE.md`](PATCH_CYCLE.md). Check these off as you go:

| TODO | 3.3.N |
|------|-------|
| Hygiene START (0 PRs, only master, tip Actions green) | |
| VERSION + Cargo `3.3.(N-1)` → `3.3.N` | |
| One-concern fix | |
| PR squash-merge + delete branch | |
| GHCR Publish `sha-<7>` | |
| Railway backup + re-pin central→mqtt→web | |
| `openfdd_fieldbus_railway_up.sh sha-<7>` | |
| `run_railway_hub_stress.sh` (CSV + ZAP) | |
| This file: new **Verdict — 3.3.N** table + artifact paths | |
| Hygiene END | |

Do **not** reopen #763 / #805 for depth. Do **not** put Pis back on the closeout path.

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.20 x86 fieldbus → Railway hub — IN FLIGHT

| Check | Evidence |
|-------|----------|
| VERSION | **3.3.20** (workspace + crates) |
| Topology | Railway hub; bensbench x86 fieldbus MQTTS only; **no Pi** |
| Field script | `scripts/openfdd_fieldbus_railway_up.sh` + `docker/compose.edge.railway.yml` |
| Stress harness | `scripts/nightly-ot-bench/run_railway_hub_stress.sh` (CSV + ZAP) |
| Rev template | [`PATCH_CYCLE.md`](PATCH_CYCLE.md) |
| GHCR / re-pin / stress artifacts | *pending publish + closeout* |
| **bldg2 Overview UI** | **DEFERRED** |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |

## Verdict — 3.3.19 utilities/export train (plan name 3.3.20, 2026-09-03) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #827 → `15baccf8`; VERSION **3.3.19**; #828 gate-19 shell; #829 agent/ops handbooks |
| Tip / pin | `0c1029da` · GHCR **`sha-0c1029d`** · health **`3.3.19+0c1029da60c7`** (local + Railway) |
| GHCR publish | **green** on tip — central/web/mqtt/fieldbus `sha-0c1029d` (nightly digest match on gate 00) |
| Railway backup | `~/openfdd-backups/railway/20260903T175358Z/` (`central-workspace.tgz` + mqtt certs) |
| Railway hub re-pin | central → mqtt → web `sha-0c1029d`; central redeploy after mqtt (ingest resume) |
| Local re-pin | `.env` `OPENFDD_IMAGE_TAG=sha-0c1029d`; `openfdd_maint_update_resume.sh react-ot sha-0c1029d --skip-maintenance` |
| bosspi fieldbus | arm64 `sha-0c1029d` (bench `docker save` load — Pi GHCR DNS timeout); `zone_other`; MQTTS connected `edge:bldg2:pi-1` |
| Pipeline A | **PASS** — `/api/health` `edges:1` `ingest_ok` advancing; `/api/edges` `pi-1` `has_telemetry:true` |
| Smoke 01/06/10/18 | **PASS** inside `run_all` + gate 18 `reports/nightly-ot-bench_20260903T180949Z/` |
| STRESS 1 `run_all` | **PASS** gates **00–16** @ `reports/nightly-ot-bench_20260903T180949Z/` (`unset SKIP_PULL`, `WEATHER_SOAK_SECS=120`). First pass gate **12 FAIL** (harness still expected 66); re-run **PASS** after registry total **68** (UTIL-MONTHLY/INTERVAL) |
| STRESS 2 synth59 | **PASS 59/59** — `reports/wattlab-parity/artifacts/synthetic_59/` |
| STRESS 3 gate 17 | **PASS** — health matrix + overview (`RUN_SYNTH59_HEALTH_MATRIX=1` in nightly `20260903T180949Z`) |
| STRESS 4 B100 | **PASS** — `reports/railway-b100-parity_20260903T182530Z/summary.json` (also copied in nightly dir). FC1 **118.42 h**, runtime **1638.75 h**, `has_confirmed_fault:true`, `poll_seconds=300` local ≡ Railway |
| STRESS 5 Creekside | **PASS** fixture + **full** `/home/ben/OpenFdd_Creekside.zip` → `LAKESIDE_ES` @ `reports/creekside-package-import_20260903T182802Z/` |
| STRESS 6 gate 19 | **PASS READY** — `reports/nightly-ot-bench_20260903T182826Z/bundle_validate.json` |
| STRESS 7 ZAP | **PASS** (light) — `reports/zap-railway_20260903T182838Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56`. No High/Critical. Accepted residuals: missing CSP / X-Frame-Options / SRI (Medium); HSTS/X-CTO/Permissions-Policy/COOP/COEP (Low); cache + plotly timestamp (Info) |
| Utilities / Export UI | `utilities_v1`; `UTIL-MONTHLY`/`UTIL-INTERVAL`; `/export`; fuel ZIP upload removed |
| **bldg2 Overview UI** | **DEFERRED** |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** — STRESS 7 is unauthenticated baseline only |

**Issues closed (foundation):** [#763](https://github.com/bbartling/open-fdd/issues/763), [#805](https://github.com/bbartling/open-fdd/issues/805) — do not reopen. ML/vibe20 depth deferred.

## Verdict — 3.3.19 remaining bugs + stress (2026-09-02) — CLOSED

| Check | Evidence |
|-------|----------|
| GHCR publish | **green** on `b565d78d` — images `sha-b565d78` |
| Railway backup | `~/openfdd-backups/railway/20260902T145413Z/` |
| Railway hub re-pin | central→mqtt→web `sha-b565d78`; health `3.3.18+b565d78d2cae` |
| Local + bosspi re-pin | `openfdd_maint_update_resume.sh react-ot sha-b565d78`; bosspi fieldbus `sha-b565d78` arm64 |
| bosspi `zone_other` | `OPENFDD_EQUIPMENT_TYPE=zone_other` in `compose.edge.local.yml` (ops, not committed) |
| Pipeline A | **PASS** — `/api/edges` → `pi-1`/`bldg2` `has_telemetry:true` @ `sha-b565d78` |
| Smoke gates | **PASS** — 01/06/10/18 (`reports/nightly-ot-bench_20260902T145608Z/` gate 18) |
| **`run_all` stress** | **PASS** — `reports/nightly-ot-bench_20260902T145737Z/` gates **00–16** (`unset SKIP_PULL`, `WEATHER_SOAK_SECS=120`) |
| Synthetic-59 target pairs | **PASS** — 59/59 @ `reports/wattlab-parity/artifacts/synthetic_59/` |
| Gate 17 health matrix | **PASS** — `RUN_SYNTH59_HEALTH_MATRIX=1` (`ofdd_health_matrix_fault_hours_checks.json`, `ofdd_overview_analytics_checks.json`) |
| BUILDING_100 Railway vs local | **PASS** — `reports/railway-b100-parity_20260902T151009Z/` (FC1 **118.42 h**, runtime **1638.75 h**, series `has_confirmed_fault:true`, `poll_seconds=300`) |
| **bldg2 Overview UI** | **DEFERRED** — env + Pipeline A verified; SPA Zone Other shells need operator browser sign-off |
| BUILDING_50 / AFDD flood | **DEFERRED** — no package on bench (operator skip) |

**Harness added:** `scripts/gates/railway_b100_parity_spot.sh` (local + Railway API capture + `summary.json`).

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
| `run_all` with GHCR pull | gate **00 pull PASS** — `20260902T123715Z/`; gate 01 fixed in **#824** merged |
| Gate 18 volume restore | **PASS** — `reports/nightly-ot-bench_20260902T124850Z/` (ingest_ok reset accepted when volume data preserved) |
| Phase 2 bench hygiene | **CLOSED** — #821 fieldbus refresh, #822 gate 03 honesty |
| **bldg2 Overview** | **DEFERRED** — `OPENFDD_EQUIPMENT_TYPE=zone_other` + UI sign-off |
| Railway F1 pipeline | **PARTIAL** — BUILDING_100 FC1 **PASS**; FDD/series spot-check + full parity in 3.3.19; BUILDING_50/AFDD **DEFERRED** |
| BUILDING_100 local vs Railway | **PASS** — FC1 AHU_1 **118.42 h** Railway @ `sha-ca67707`; artifact `reports/railway-f1-spot_20260902T124900Z/` |

## Verdict — 3.3.18 closeout (2026-09-02 early)

| Check | Evidence |
|-------|----------|
| Local `run_all` (harness-only pin) | **PASS** — `reports/nightly-ot-bench_20260902T013750Z/` gates **01–16** on `sha-3e35b2d` images |

## BUILDING_100 — local vs Railway parity (2026-09-02 @ sha-b565d78)

| Field | Local | Railway | Tolerance |
|-------|-------|---------|-----------|
| FC1 AHU_1 `fault_hours` | 118.42 h | 118.42 h | ±0.05 h |
| AHU_1 `run_hours` | 1638.75 h | 1638.75 h | ±0.01 h |
| `poll_seconds` | 300 | 300 | exact |
| `fdd/series` `has_confirmed_fault` | true | true | exact |

**Artifact:** `reports/railway-b100-parity_20260902T151009Z/` (prior `reports/railway-b100-parity_20260901T190000Z/`, spot `reports/railway-f1-spot_20260902T124900Z/`).

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
| **Railway hub + x86 field** (3.3.20+) | **IN FLIGHT** — bensbench fieldbus → MQTTS; Pis removed from stress |
| **A Cloud** bosspi → Railway (historical) | **PASS** last @ `sha-0c1029d` — **retired** for closeout |
| **B Local** react-ot (historical) | **PASS** last `20260903T180949Z` — **lab only**, not closeout |

## Patch cycle — Phase 7 + phase2 bench hygiene (2026-09-01 → 2026-09-02)

| Gate / ID | Symptom | Status on tip harness |
|-----------|---------|------------------------|
| **#528** poll_seconds | harness `poll_seconds=300` | **PATCHED 3.3.16** — gate 06 `poll_seconds≈60` on CSV fixture |
| **fieldbus-poll-stale** | `points_polled:0` after long sessions | **PATCHED 3.3.17** — `recreate_bench_fieldbus` |
| **gate03-ingest-counter** | ingest counter unchanged despite live MQTTS | **PATCHED 3.3.18** |
| **playwright-workflows** | `/rules` redirect + auth timing | **PATCHED 3.3.16** — #818 |
| **gate01-fieldbus-starting** | gate 01 FAIL after fieldbus recreate (`health=starting`) | **PATCHED harness** — #824 merged |
| **gate18-ingest-counter** | gate 18 FAIL on ingest_ok reset after central recreate | **PATCHED harness** — #824 merged |
| **weather-legitimacy** | Chicago Δ>3°F on short soak | **OPEN** tier-C — passed on short soak runs |

**Artifacts:**

| Pin | Artifact | Result |
|-----|----------|--------|
| `sha-b565d78` | `reports/nightly-ot-bench_20260902T145737Z/` | **PASS** gates 00–16 (pull + stress) |
| `sha-b565d78` | `reports/railway-b100-parity_20260902T151009Z/` | **PASS** B100 Railway vs local |
| `sha-b565d78` | `reports/wattlab-parity/artifacts/synthetic_59/` | **PASS** synthetic-59 59/59 + gate 17 |
| `sha-ca67707` | `reports/nightly-ot-bench_20260902T125016Z/` | **PASS** gates 01–16 |
| `sha-ca67707` | `reports/nightly-ot-bench_20260902T123715Z/` | gate 00 pull PASS; gate 01 FAIL (pre-harness fix) |
| `sha-3e35b2d` | `reports/nightly-ot-bench_20260902T013750Z/` | **PASS** gates 01–16 (harness on old images) |

## Railway F1 pipeline (separate tier — BUILDING_100 closed)

| Check | Last evidence |
|-------|---------------|
| Hub health | `3.3.18+b565d78d2cae`, `edges:1`, `ingest_ok` advancing |
| **BUILDING_100 FC1 + series + runtime** | **PASS** 2026-09-02 @ `sha-b565d78` — `reports/railway-b100-parity_20260902T151009Z/` |
| FDD run + series spot-check | **PASS** — `railway_b100_parity_spot.sh` (not rule_id DF55) |
| BUILDING_50 CSV import + FDD | **DEFERRED** — no package on bench |
| AFDD flood | **DEFERRED** — operator skip |
| bldg2 Overview UI | **DEFERRED** — `OPENFDD_EQUIPMENT_TYPE=zone_other` + Pipeline A; SPA browser sign-off pending |

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
| **bldg2-overview-signoff** | `OPENFDD_EQUIPMENT_TYPE=zone_other` + bosspi `sha-0c1029d` + Pipeline A PASS; SPA Zone Other shells need operator browser confirm |
| **railway-f1-stress** | B100 parity **PASS** @ `20260902T151009Z`; B50/AFDD **DEFERRED** |
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
2. Re-pin order: central → mqtt → web, then `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` on this x86 host.  
3. After mqtt/central redeploy: `railway redeploy -s openfdd-central-cQ-F` if `edges:0` persists.  
4. Do **not** bring local `react-ot` or Raspberry Pi fieldbus back for closeout.  
5. Full stress **LAST**: `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` (CSV synth59 + gate 17 + B100 `RAILWAY_ONLY=1` + Creekside + gate 19 + light ZAP).  
6. `OPENFDD_PARQUET_ROOT=/workspace/openfdd` on Railway when `STORAGE_URL=file:///workspace/openfdd`.
