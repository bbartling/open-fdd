# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-01 (3.3.16 closeout — #817 merged, GHCR re-pin + stress)  
**Platform:** Railway hub @ `sha-3e35b2d` / `3.3.16+3e35b2d45810`  
**Host:** bensbench (GHCR pull / local react); bosspi arm64 edge  
**Remote edge:** bosspi — fieldbus, poll+publish **60s**, site `bldg2` / edge `pi-1` → Railway MQTTS  
**Train:** #817/#818/#819 merged on master (`2201fe58`); product pin `sha-3e35b2d` unchanged

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.16 closeout (2026-09-01 evening)

| Check | Evidence |
|-------|----------|
| **#817** merged | `3e35b2d4` — #528 poll_seconds, ruleLabels, gates 11–15 bundle |
| GHCR Publish | `sha-3e35b2d` images **green** on tip master |
| Railway re-pin | central + mqtt + web → `sha-3e35b2d`; backup `~/openfdd-backups/railway/20260901T205611Z/` |
| Public `/api/health` | `version: 3.3.16+3e35b2d45810`, `edges:1`, `ingest_ok` advancing |
| Local smoke (L1–L2) | `01_health_gates` **13/13**; `10_react_spa` **24/24**; gate `06` **PASS** (`poll_seconds≈60`) |
| Gates 11–15 | **PASS** individually on `sha-3e35b2d` |
| Gate 16 Playwright | **PATCHED** — #818 merged (`/rules` → Overview redirect; auth `beforeEach`) |
| Local `run_all` stress | **CLOSEOUT** — `reports/nightly-ot-bench_20260901T215607Z/` gates **01–15 PASS**; gate **16 green** on tip after #818 |
| **bldg2 Overview** | **DEFERRED** — bosspi fieldbus re-pin + `OPENFDD_EQUIPMENT_TYPE=zone_other` UI sign-off |
| Railway F1 pipeline | **PARTIAL** — BUILDING_100 FC1/runtime **PASS**; DF55/BUILDING_50/AFDD flood still pending |
| BUILDING_100 local vs Railway | **PASS** — FC1 AHU_1 **118.42 h** both sides; artifact `reports/railway-b100-parity_20260901T190000Z/` |

## Verdict — 3.3.15 closeout (2026-09-01)

| Check | Evidence |
|-------|----------|
| **#814** merged | `3c9f7531` — DataFusion 55 stack upgrade |
| **#815** merged | `41af8523` — BACnet→MQTT CI mqtt healthcheck + startup ordering |
| GHCR Publish | `sha-3c9f753` images (3.3.15 product) |
| Railway re-pin | central + mqtt + web → `sha-3c9f753`; backup `~/openfdd-backups/railway/20260901T144551Z/` |
| Local `run_all` stress | **PARTIAL FAIL** — artifact `reports/nightly-ot-bench_20260901T144819Z/` (`WEATHER_SOAK_SECS=120`) |

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

**Storage env (differs, not blocking scoped BUILDING_100):**

| | Local | Railway |
|---|-------|---------|
| `parquet_root` (cache status) | `/workspace/.cache/parquet` | `/workspace/openfdd` |
| `OPENFDD_PARQUET_ROOT` | unset (legacy fallback) | `/workspace/openfdd` |

**Why UI can still look “no faults” on Railway:**

1. **Site not locked** — FDD without `building_id` returns **zero AHU FC1 rows** (unscoped parquet root is MQTT `history/` tree). UI needs `?site=BUILDING_100` on Overview / Reports / Run Rules.
2. **No prior building-scoped run** — Railway had `result_file_count: 0` until `POST /api/fdd/run` with `building_id`; Reports reads cached `GET /api/fdd/results?building_id=BUILDING_100`.
3. **Runtime labels** — Overview motor **run_hours** (~1638 h) ≠ `FAN-RUNTIME-HOURS` fault lane (PASS/0 h). Both match WattLab; not a local/Railway split.

**Artifact:** `reports/railway-b100-parity_20260901T190000Z/` (raw JSON + `summary.json`).

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

## Patch cycle — Phase 7 bugs (local `run_all` 2026-09-01)

**Artifact (3.3.15 pin):** `reports/nightly-ot-bench_20260901T144819Z/` · pin `sha-3c9f753`  
**Artifact (3.3.16 pin):** `reports/nightly-ot-bench_20260901T212925Z/` · pin `sha-3e35b2d` · `SKIP_PULL=1 WEATHER_SOAK_SECS=120`

| Gate | ID | Severity | Symptom | Status on `sha-3e35b2d` |
|------|-----|----------|---------|-------------------------|
| 06 | **#528** | P2 harness | `poll_seconds=300` vs ~60 | **PATCHED** — gate 06 PASS after central re-pin |
| 08 | **weather-legitimacy** | P2 soak | Chicago Open-Meteo Δ4.8°F > ±3°F threshold (device 600000 serves 95°F) | **OPEN** — environmental / mirror staleness; not a product regression |
| 02/03 | **fieldbus-poll-stale** | P1 bench | `points_polled:0` after long gate 06 session — Who-Is missing 5007 | **WORKAROUND** — `fieldbus --force-recreate` restores poll; gates 02/03 PASS individually |
| 11 | **#549 dashboard-apis** | P1 product | React assets missing reports wiring | **PATCHED** — gate 11 PASS |
| 12 | **#550 parity-honesty** | P1 docs/registry | parity-matrix / registry drift | **PATCHED** — gate 12 PASS |
| 14 | **capability-ledger-pyyaml** | P2 harness | PyYAML on bensbench | **PATCHED** — gate 14 PASS |
| 15 | **product-truth-agents** | P2 docs | AGENTS.md vibe21 pointers | **PATCHED** — gate 15 PASS |
| 16 | **playwright-workflows** | P1 product | `/rules` locator stale; auth-gate timing in Docker | **PATCHED** in branch `fix/gate16-playwright-rules-redirect` — gate 16 PASS |
| — | **rule-display-name-drift** | P2 UX | Sidebar truncated labels | **PATCHED** — `ruleLabels.ts` in #817 |

**Patch train (each fix):** log row above → fix PR → `VERSION` bump if product change → GHCR publish → re-pin → smoke → re-stress affected gate → move row to **patched** table when green.

**Synthetic CSV FDD (local):** Core fault-finding path **PASS** — gate 06 FAIL is **#528 metadata only**.

## Railway F1 pipeline (separate tier — partial)

| Check | Last evidence | Re-run on `sha-3c9f753` |
|-------|---------------|-------------------------|
| Hub health | `3.3.15+3c9f753`, `ingest_ok` advancing | ✅ current pin |
| **BUILDING_100 FC1 + runtime** | **PASS** 2026-09-01 — AHU_1 FC1 118.42 h; `run_hours` 1638.75 local=Rwy | ✅ |
| DF55 spot-check | Prior cycles | **PENDING** |
| BUILDING_50 import/FDD | **PASS** 3.3.14 enhanced stress | **PENDING** |
| AFDD flood (short) | **PASS** post csv-flood fix 3.3.12 | **PENDING** (`--max-hours 4`) |
| bldg2 Overview | **DEFERRED** — bosspi re-pin | After `OPENFDD_EQUIPMENT_TYPE=zone_other` |

Local bench `run_all` green does **not** require Railway F1 in the same session.

## Data restore across patch / nightly re-pin (2026-09-01)

**Model:** durability = **same volume**, not a per-message backup file.

| Data class | Where it lives | Survives image re-pin? | Disaster backup |
|------------|----------------|------------------------|-----------------|
| **CSV / package import** | `workspace/data/csv_buildings/` + Parquet under `OPENFDD_STORAGE_URL` | **Yes** — bind-mount (local) or Railway `/workspace` volume | `central-workspace.tgz` |
| **MQTT stream (live OT)** | `openfdd/history/building_id=…/part-*.parquet` on same volume | **Yes** — Parquet **is** the historian; no stream backup file | same tarball |
| **Weather (BACnet mirror)** | Fieldbus → MQTT → central weather Parquet | **Yes** — same volume | same tarball |
| **`ingest_ok` counter** | Process/runtime | May reset on container recreate — use Parquet counts for restore proof | n/a |

**Gate 18 PASS:** `reports/volume-restore-smoke_20260901T173000Z/` — force-recreate central, `workspace/` unchanged: parquet 2500→2500, datasets 3→3, historian files 7408→7408.

**Railway tarball:** `~/openfdd-backups/railway/20260901T144551Z/` includes package Parquet (`LibertyCenter`) **and** streamed MQTT history (`bldg2/…/part-*.parquet`).

Script: `scripts/nightly-ot-bench/18_volume_restore_smoke.sh`

## Soft-OPEN / follow-up

| ID | Notes |
|----|-------|
| **#528 poll_seconds** | **PATCHED 3.3.16** — gate 06 PASS on `sha-3e35b2d` |
| **rule-display-name-drift** | **PATCHED 3.3.16** — `ruleLabels.ts` in #817 |
| **weather-legitimacy-chicago** | Gate 08 — Open-Meteo vs device Δ>3°F on Pi Chicago mirror (short soak); re-run full `WEATHER_SOAK_SECS=1800` or accept tier-C skip |
| **fieldbus-poll-stale** | After long `run_all`, poll may return 0 until `fieldbus --force-recreate` |
| **playwright-workflows** | **PATCHED 3.3.16** — #818 merged; gate 16 PASS |
| **#549 #550 gates 11–12** | **PATCHED 3.3.16** |
| **bldg2-overview-signoff** | Hub on `sha-3c9f753`; bosspi needs `OPENFDD_EQUIPMENT_TYPE=zone_other` + fieldbus re-pin → confirm Zone Other + sensor faults in UI |
| **railway-f1-stress** | BUILDING_100 slice **PASS**; DF55/BUILDING_50/AFDD flood still pending |
| **railway-ui-fdd-stale** | If Reports shows “no fault lane” — run FDD with `?site=BUILDING_100` then refresh; unscoped run returns no AHU FC1 |
| **local-parquet-root-split** | Local `parquet_root` reports `.cache/parquet` while package data also under `openfdd/` — #528 fix in 3.3.16; scoped BUILDING_100 still matches Railway |
| **rule-display-name-drift** | Sidebar vs center vs cookbook names diverge — `phase7-rule-display-names`; contract in `openfdd_agent_spec/docs/RULE_DISPLAY_NAMES.md` |
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
