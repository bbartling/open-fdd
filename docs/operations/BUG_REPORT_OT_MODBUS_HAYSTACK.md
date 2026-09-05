# BUG REPORT — OT Modbus / Haystack / BACnet / MQTT (low-RAM GHCR loop)

**Date:** 2026-09-05 (3.3.24 CLOSED — GL36 Lab tuners; hybrid GHCR pin)  
**Platform:** Railway hub + bensbench **x86 fieldbus only** (no Raspberry Pi in stress)  
**Tip / pin (closeout claim):** `72b22995` · GHCR central/web **`sha-72b2299`** · health **`3.3.24+72b2299541e9`** (mqtt/fieldbus **`sha-b3004aa`** — DEFERRED tip sync)  
**Field:** bensbench x86 `openfdd-fieldbus` → Railway MQTTS (`bldg2` / client `pi-1` kit reused — Railway mqtt volume has CA cert but no CA key, so a newly minted `bensbench-1` kit will not verify). Telemetry = hosted weather AV `9101` loopback (no Pi, no JCI required).  
**Pis freed (not in stress):** bosspi · BensFakeAhu (fake AHU) · Zone1VAV (fake VAV) — vibe13 / other. Private OT LAN addresses stay in session env only.

## Next patch cycle (copy into `.cursor/plans/patch_cycle_3.3.N_<slug>.plan.md`)

Template + commands: [`PATCH_CYCLE.md`](PATCH_CYCLE.md). Check boxes as you go. Do **not** bump VERSION for a pure evidence/docs PR.

### Upcoming trains (Cursor plans — 2026-09-04)

**Source of truth in-repo (survives laptop death):** [`patch_trains/`](patch_trains/) · machine recreate [`BENCH_RECOVERY.md`](BENCH_RECOVERY.md) · AI handoff [`recovery/AI_CONTEXT_HANDOFF.md`](recovery/AI_CONTEXT_HANDOFF.md).  
Optional local Cursor copies: `~/.cursor/plans/` (keep in sync with `patch_trains/`).  
Topology: Railway hub + bensbench **x86 fieldbus** + light ZAP. **Skip** only with a **DEFERRED** row here.

| Rev | In-repo plan | Concern | Status |
|-----|--------------|---------|--------|
| 3.3.21 closeout | [`patch_trains/3.3.21_closeout_railway_stress.plan.md`](patch_trains/3.3.21_closeout_railway_stress.plan.md) | Re-pin + stress + Verdict (product already merged) | **CLOSED** |
| 3.3.22 | [`patch_trains/3.3.22_one_dump_ia.plan.md`](patch_trains/3.3.22_one_dump_ia.plan.md) | One **Dump** page; ingest left-rail only; kill Export&ML multi-page | **CLOSED** |
| 3.3.23 | [`patch_trains/3.3.23_faults_lab_declutter.plan.md`](patch_trains/3.3.23_faults_lab_declutter.plan.md) | Faults/Lab declutter (category-first; less settings-on-faults) | **CLOSED** |
| 3.3.24 | [`patch_trains/3.3.24_tuners_gl36_wave.plan.md`](patch_trains/3.3.24_tuners_gl36_wave.plan.md) | Lab/registry GL36 FC thresholds (SQL-honest) | **CLOSED** |
| 3.3.25 | [`patch_trains/3.3.25_tuners_sv_econ_ahu_wave.plan.md`](patch_trains/3.3.25_tuners_sv_econ_ahu_wave.plan.md) | Lab/registry SV/ECON/AHU/plant gaps | PENDING |
| 3.3.26 | [`patch_trains/3.3.26_tuners_gates_residual.plan.md`](patch_trains/3.3.26_tuners_gates_residual.plan.md) | Optional gate trio + soft-OPEN triage + series wrap | PENDING |

**Tuner reference:** Vibe19 UI ~414 vs Lab ~184 — JSON snapshots in [`recovery/`](recovery/). Goal = phased SQL-honest Lab expansion — **not** a hard 414.

| TODO | 3.3.23 | 3.3.24 |
|------|--------|--------|
| Hygiene START | [x] | [x] |
| VERSION bump | [x] #840 | [x] #842 |
| One-concern fix | [x] Lab declutter | [x] GL36 Lab tuners |
| PR squash-merge | [x] #840 | [x] #842 |
| GHCR full stack tip | [~] hybrid | [~] central/web `sha-72b2299`; mqtt/fieldbus DEFERRED |
| Railway backup + re-pin | [x] | [x] `20260905T034509Z` |
| Stress CSV + ZAP | [x] | [x] |
| Verdict | [x] | [x] |

Do **not** reopen #763 / #805 for depth. Do **not** put Pis back on the closeout path.

Private OT LAN addresses, vendor lake credentials, and tunnel endpoints live only in session env / gitignored files — **never Discord→git**.

**Canonical file:** [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](./BUG_REPORT_OT_MODBUS_HAYSTACK.md)

## Verdict — 3.3.24 GL36 Lab tuners (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #842 → `72b22995`; VERSION **3.3.24** |
| Tip / pin | central/web **`sha-72b2299`** · health **`3.3.24+72b2299541e9`** |
| Shipped | FC2/3/5/8–12 SQL-honest Lab params (`MIX_TOL`, `DELTA_SUPPLY_FAN`, econ/clg thresholds, …); defaults = prior literals |
| GHCR | central+web tags OK; mqtt/fieldbus Publish still slow/hung — **DEFERRED** tip sync |
| Railway backup | `~/openfdd-backups/railway/20260905T034509Z/` |
| Fieldbus | `sha-b3004aa` (prior); `edges:1` |
| STRESS | **PASS** — `reports/nightly-ot-bench_20260905T035119Z/` (first `034632Z` 00 FAIL edges race; re-run PASS) |
| ZAP | **PASS** — `reports/zap-railway_20260905T035155Z/` · `FAIL-NEW:0` |
| Gate trio / mode_delay | **DEFERRED** → 3.3.26 |
| mqtt/fieldbus tip pin | **DEFERRED** |

## Verdict — 3.3.23 Faults/Lab declutter (2026-09-05) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #840 → `40ac0664`; VERSION **3.3.23** |
| Tip / pin | central/web `40ac0664` · **`sha-40ac066`** · health **`3.3.23+40ac06640af4`** |
| GHCR | central + web tags **green**; mqtt + fieldbus Publish hung on multi-arch fieldbus build (runs `33927904427`, `33934657485` cancelled) |
| Railway backup | `~/openfdd-backups/railway/20260905T021711Z/` |
| Hub re-pin | central + web → `sha-40ac066`; mqtt left on `sha-b3004aa` |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-b3004aa` (prior tip); `edges:1` |
| STRESS 0–6 | **PASS** — `reports/nightly-ot-bench_20260905T021921Z/` |
| ZAP | **PASS** — `reports/zap-railway_20260905T021959Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56` |
| Shipped | Lab default category FC/VAV; `FC*` grouped as family FC; Results/Plots/Overview Run vs Tune vs Update analytics copy |
| **mqtt/fieldbus tip pin sync** | **DEFERRED** → next Publish success or 3.3.24 re-pin (same sha) |
| **bldg2 Overview UI** | **DEFERRED** → 3.3.26 |

## Verdict — 3.3.22 One Dump IA (2026-09-04) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #838 → `b3004aa3`; VERSION **3.3.22** |
| Topology | Railway hub only; bensbench x86 fieldbus MQTTS; **no Pi** |
| Tip / pin | `b3004aa3` · GHCR **`sha-b3004aa`** · health **`3.3.22+b3004aa33bc2`** |
| GHCR publish | **green** — run `33915988499` central/web/mqtt/fieldbus `sha-b3004aa` |
| Railway backup | `~/openfdd-backups/railway/20260904T222234Z/` |
| Railway hub re-pin | central → mqtt → web `sha-b3004aa` |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-b3004aa`; health `edges:1`; `ingest_ok` advancing |
| STRESS 0–6 | **PASS** — `reports/nightly-ot-bench_20260904T222851Z/` (first attempt `222500Z` FAIL: local `.env` clobbered Railway admin → 401; re-run with Railway `OPENFDD_ADMIN_PASSWORD`) |
| STRESS 6 ZAP | **PASS** (light) — `reports/zap-railway_20260904T222928Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56` |
| Shipped | Nav **Dump**; single dump workflow (no Uploads/Fuel/Twin/ECM radio); ingest via Upload/Sites; Metering package utilities |
| Harness note | Do **not** source local `.env` over Railway admin for hub stress |
| **bldg2 Overview UI** | **DEFERRED** → 3.3.26 |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |
| WattLab ML depth (#763) | **DEFERRED** (explicit non-goal) |

## Verdict — 3.3.21 Overview / MQTT / Metering closeout (2026-09-04) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #833 → `792ebeec` (plus #835 PayPal polish on tip used for pin); VERSION **3.3.21** |
| Topology | Railway hub only; bensbench x86 fieldbus MQTTS; **no Pi** |
| Field identity | `bldg2` / `pi-1` kit (CA reuse); hosted-weather AV 9101 loopback |
| Tip / pin (closeout) | `792ebeec` · GHCR **`sha-792ebee`** · health **`3.3.21+792ebeec4be3`** |
| Docs tip note | #836 paypal.me + #837 recovery pack later on master — **not** used for closeout pin identity |
| GHCR publish | **green** — central/web/mqtt/fieldbus `sha-792ebee` |
| Railway backup | `~/openfdd-backups/railway/20260904T193732Z/` |
| Railway hub re-pin | central → mqtt → web `sha-792ebee`; central redeploy after mqtt |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-792ebee`; health `edges:1`; `ingest_ok` advancing |
| STRESS 0 hub + edges | **PASS** — `reports/nightly-ot-bench_20260904T194123Z/` |
| STRESS 1 synth59 | **PASS** — same dir `01_synth59_Railway.log` |
| STRESS 2 gate 17 | **PASS** — `02_gate_17.log` |
| STRESS 3 B100 | **PASS** — `03_B100_Railway-only.log` |
| STRESS 4 Creekside | **PASS** — `04_Creekside.log` |
| STRESS 5 gate 19 | **PASS** — `05_gate_19.log` + `bundle_validate.json` |
| STRESS 6 ZAP | **PASS** (light) — `reports/zap-railway_20260904T194203Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56`. No High/Critical |
| Shipped (product) | Overview readiness A–Z; MQTT Zone Other; Metering package utilities |
| **bldg2 Overview UI** site cleanup | **DEFERRED** → revisit 3.3.26 soft-OPEN |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |

## Verdict — 3.3.20 x86 fieldbus → Railway hub (2026-09-04) — CLOSED

| Check | Evidence |
|-------|----------|
| Product merge | #831 → `aef6fc1f`; VERSION **3.3.20** |
| Topology | Railway hub only; bensbench x86 fieldbus MQTTS; **no Pi** |
| Field identity | `bldg2` / `pi-1` kit (CA reuse); `config/fieldbus/field_devices.toml` hosted-weather `127.0.0.1` AV 9101 |
| Tip / pin | `aef6fc1f` · GHCR **`sha-aef6fc1`** · health **`3.3.20+aef6fc1f5b29`** (central + web `version.json`) |
| GHCR publish | **green** — central/web/mqtt/fieldbus `sha-aef6fc1` |
| Railway backup | `~/openfdd-backups/railway/20260904T035328Z/` |
| Railway hub re-pin | central → mqtt → web `sha-aef6fc1`; central redeploy after mqtt (ingest resume) |
| x86 fieldbus | `openfdd_fieldbus_railway_up.sh sha-aef6fc1`; MQTTS connected; `/api/edges` `pi-1` `has_telemetry:true` |
| STRESS 0 hub + edges | **PASS** — `reports/nightly-ot-bench_20260904T040851Z/` |
| STRESS 1 synth59 | **PASS 59/59** — `reports/wattlab-parity/artifacts/synthetic_59/` |
| STRESS 2 gate 17 | **PASS** (re-run after Railway admin not clobbered by local `.env`) — `reports/railway-hub-rerun_20260904T041358Z/` |
| STRESS 3 B100 | **PASS** `RAILWAY_ONLY=1` — FC1 **118.42 h**, runtime **1638.75 h**, `has_confirmed_fault:true`, `poll_seconds=300` @ `20260904T040851Z/summary.json` |
| STRESS 4 Creekside | **PASS** fixture + full zip → `LAKESIDE_ES` @ `reports/railway-hub-rerun_20260904T041358Z/` |
| STRESS 5 gate 19 | **PASS READY** — same rerun dir `bundle_validate.json` |
| STRESS 6 ZAP | **PASS** (light) — `reports/zap-railway_20260904T040909Z/` · `FAIL-NEW:0` / `WARN-NEW:11` / `PASS:56`. No High/Critical. Same header residuals as prior cycle |
| Rev template | [`PATCH_CYCLE.md`](PATCH_CYCLE.md) |
| **bldg2 Overview UI** | **DEFERRED** |
| BUILDING_50 / AFDD flood | **DEFERRED** |
| Deep / authenticated ZAP | **DEFERRED** |

Harness note: `RAILWAY_ONLY=1` must keep `RAILWAY_ADMIN_PASSWORD` after sourcing local `.env` (`lib.sh` + Creekside spot).

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
| **Railway hub + x86 field** (3.3.20+) | **PASS** @ `sha-aef6fc1` — hosted-weather loopback → MQTTS; Pis removed from stress |
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
