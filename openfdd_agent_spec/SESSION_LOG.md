# Session log

## 2026-09-05 — 3.3.23 Faults/Lab declutter CLOSED

- **Merge:** #840 → `40ac0664`; VERSION **3.3.23**; health **`3.3.23+40ac06640af4`**.
- **Pin:** central/web **`sha-40ac066`**; mqtt/fieldbus remained **`sha-b3004aa`** (GHCR fieldbus multi-arch Publish hung — DEFERRED tip sync).
- **Backup:** `~/openfdd-backups/railway/20260905T021711Z/`. Stress `reports/nightly-ot-bench_20260905T021921Z/` PASS; ZAP `reports/zap-railway_20260905T021959Z/`.
- **Shipped:** Lab category-first FC/VAV; FC* family grouping; Run vs Tune vs Update analytics copy.
- Next: 3.3.24 GL36 Lab tuners (branch `feat/3.3.24-tuners-gl36` ready).

## 2026-09-04 — 3.3.23 Faults/Lab declutter (product)

- VERSION **3.3.23**; Lab defaults to FC/VAV category; group `FC*` under family FC; Results/Plots copy clarifies Lab vs outcomes; Overview Start-here Run vs Update analytics.

## 2026-09-04 — 3.3.22 One Dump IA CLOSED

- **Merge:** #838 → `b3004aa3`; VERSION **3.3.22**; pin **`sha-b3004aa`**; health **`3.3.22+b3004aa33bc2`**.
- **Backup:** `~/openfdd-backups/railway/20260904T222234Z/`. Hub re-pin central→mqtt→web; x86 `openfdd_fieldbus_railway_up.sh sha-b3004aa`.
- **STRESS:** `reports/nightly-ot-bench_20260904T222851Z/` PASS 00–06; ZAP `reports/zap-railway_20260904T222928Z/` (`FAIL-NEW:0`). First stress `222500Z` failed on Railway admin clobbered by local `.env`.
- **Shipped:** Dump nav + single dump page; ingest left-rail Upload/Sites only.
- Next: 3.3.23 Faults/Lab declutter.

## 2026-09-04 — 3.3.21 closeout CLOSED + 3.3.22 Dump IA (product)

- **Closeout pin:** `792ebeec` / **`sha-792ebee`** / health **`3.3.21+792ebeec4be3`**. Backup `~/openfdd-backups/railway/20260904T193732Z/`. Stress `reports/nightly-ot-bench_20260904T194123Z/` + ZAP `reports/zap-railway_20260904T194203Z/` (`FAIL-NEW:0`).
- **DEFERRED:** bldg2 Overview site cleanup → 3.3.26; B50; deep ZAP.
- **3.3.22 product:** VERSION **3.3.22**; nav **Dump**; single dump workflow (no Uploads/Fuel/Twin/ECM radio); ingest via Upload / Sites only; Metering keeps package utilities.
- Next after merge: GHCR → Railway re-pin → stress → Verdict 3.3.22 → then 3.3.23 Faults Lab declutter.

## 2026-09-04 — Bench recovery pack + patch trains mirrored in-repo

- Added `docs/operations/BENCH_RECOVERY.md`, `docs/operations/recovery/AI_CONTEXT_HANDOFF.md`
- Mirrored Cursor plans → `docs/operations/patch_trains/` (3.3.21 closeout … 3.3.26)
- Tuner snapshots: Lab ~184 (`lab_tuners_snapshot_pre_3.3.24.json`), Vibe19 UI ~414 (`vibe19_ui_tuners_snapshot.json`)
- BUG_REPORT / PATCH_CYCLE / STRESS_CLOSEOUT link to in-repo trains + recovery
- Operator still must off-box copy: Railway backups, mqtt edge kit, Creekside zip, tokens


## 2026-09-04 — 3.3.20 x86 field → Railway hub CLOSED

- **Merge:** #831 → `aef6fc1f`; VERSION **3.3.20**; pin **`sha-aef6fc1`**; health **`3.3.20+aef6fc1f5b29`**.
- **Backup:** `~/openfdd-backups/railway/20260904T035328Z/`. Hub re-pin central→mqtt→web; x86 `openfdd_fieldbus_railway_up.sh sha-aef6fc1`.
- **Field:** MQTTS `bldg2`/`pi-1` kit; hosted-weather AV 9101 loopback (no Pi). `/api/edges` `has_telemetry:true`.
- **STRESS:** `reports/nightly-ot-bench_20260904T040851Z/` (00, synth59 59/59, B100, ZAP `FAIL-NEW:0`); rerun `reports/railway-hub-rerun_20260904T041358Z/` (gate 17 + Creekside + gate 19) after Railway admin preserved over local `.env`.
- Pis (bosspi / BensFakeAhu / Zone1VAV) stay off the closeout path.
- Next rev: copy [`PATCH_CYCLE.md`](../docs/operations/PATCH_CYCLE.md) YAML → `.cursor/plans/patch_cycle_3.3.21_<slug>.plan.md`.

## 2026-09-03 — 3.3.20 VERSION + x86 field → Railway hub (start)

- Bump **3.3.19 → 3.3.20**. Closeout path is Railway hub + bensbench fieldbus only.
- Raspberry Pis (bosspi / BensFakeAhu / Zone1VAV) **out** of Open-FDD stress (vibe13 / other).
- Harness: `openfdd_fieldbus_railway_up.sh`, `run_railway_hub_stress.sh`, [`PATCH_CYCLE.md`](../docs/operations/PATCH_CYCLE.md).
- Prior utilities train remains CLOSED @ `d83dbf91` / `sha-0c1029d`.

## 2026-09-03 — 3.3.20 stress closeout CLOSED

- **Pin:** `sha-0c1029d` / `3.3.19+0c1029da60c7` on Railway (central→mqtt→web), local react-ot, bosspi fieldbus arm64.
- **Backup:** `~/openfdd-backups/railway/20260903T175358Z/`.
- **Pipeline A:** mqtt `edge:bldg2:pi-1` TLS; `/api/edges` `has_telemetry:true`; `ingest_ok` after central redeploy.
- **STRESS 1:** `reports/nightly-ot-bench_20260903T180949Z/` gates 00–16 (gate 12 re-run after registry total 68).
- **STRESS 2–3:** synth59 **59/59** + gate 17 PASS (`reports/wattlab-parity/artifacts/synthetic_59/`).
- **STRESS 4:** B100 local ≡ Railway — `reports/railway-b100-parity_20260903T182530Z/` (FC1 118.42 h / runtime 1638.75 h).
- **STRESS 5–6:** Creekside fixture + full zip `20260903T182802Z`; gate 19 READY `20260903T182826Z`.
- **STRESS 7:** ZAP baseline `reports/zap-railway_20260903T182838Z/` — no High/Critical; header residuals accepted.
- Living evidence: [`BUG_REPORT`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md).

## 2026-09-03 — Agent ops docs: stress + local/Railway bootstrap

- Added [`docs/operations/STRESS_CLOSEOUT.md`](../docs/operations/STRESS_CLOSEOUT.md) (STRESS 1–7 incl. light OWASP ZAP) + skill `openfdd-stress-closeout`.
- Added [`docs/operations/LOCAL_DEPLOYMENT.md`](../docs/operations/LOCAL_DEPLOYMENT.md) — firewall hub, **HTTP only / no product TLS yet**.
- Wired AGENTS.md rules 49–50, railway-cli / stack-ghcr skills, `mcp/README.md` + `INSTRUCTIONS.md`, `RAILWAY_DEPLOYMENT.md` related-docs table.
- Plan stress remaining: `.cursor/plans/3.3.20_engineering_ml_bundle_utilities.plan.md` (do not start stress in this docs pass).

## 2026-09-02 (evening) — 3.3.20 engineering export + utilities closeout

- **Merge:** #827 → `15baccf8`; VERSION **3.3.19**; Export & ML UI, `openfdd_engineering_bundle_v1`, `utilities_v1`, Creekside nested import, `UTIL-MONTHLY`/`UTIL-INTERVAL`.
- **GHCR + re-pin:** `sha-15baccf`; local react `openfdd_maint_update_resume.sh react-ot sha-15baccf --skip-maintenance`; health `3.3.19+15baccf84e24`.
- **Gates:** Creekside import **PASS** (`reports/creekside-package-import_20260902T230020Z/`); gate 19 bundle validator **READY** (`reports/nightly-ot-bench_20260902T230020Z/`).
- **Hotfix:** #828 — gate 19 jq `NOT_READY` quote + `PASS` counter shadow fix.
- **Issues closed:** #763, #805.
- **GH hygiene END:** 0 open PRs after #828 merge; only `master`.
- **Note:** full stress matrix (`run_all` / synth59 / B100 / ZAP) still pending per STRESS_CLOSEOUT — BUG_REPORT 3.3.20 verdict still thin until then.
- Plan: `.cursor/plans/3.3.20_engineering_ml_bundle_utilities.plan.md`

## 2026-09-02 (afternoon) — 3.3.20 engineering export + utilities (in flight)

- **Branch:** `fix/3.3.20-engineering-ml-export` — nested Creekside import, `utilities_v1`, Rust `openfdd_engineering_bundle_v1`, Export & ML UI, `UTIL-MONTHLY`/`UTIL-INTERVAL`, gate 19 + Creekside spot.
- **VERSION:** `3.3.19`
- **Pending closeout:** merge PR → GHCR publish → re-pin → stress (`run_all` + gate 19 + Creekside import) → BUG_REPORT final → GH hygiene END.
- Plan: `.cursor/plans/3.3.20_engineering_ml_bundle_utilities.plan.md`

## 2026-09-02 (afternoon) — 3.3.19 remaining bugs + stress closeout

- **GH hygiene START:** 0 open PRs; only `master`; tip Actions green.
- **GHCR + re-pin:** `sha-b565d78` / `3.3.18+b565d78d2cae` on Railway (central→mqtt→web), local react, bosspi fieldbus arm64; backup `~/openfdd-backups/railway/20260902T145413Z/`.
- **bosspi bldg2:** `OPENFDD_EQUIPMENT_TYPE=zone_other` in `compose.edge.local.yml` (ops); Pipeline A **PASS** (`pi-1`/`bldg2` `has_telemetry:true`).
- **Smoke:** gates 01/06/10/18 PASS before stress (`reports/nightly-ot-bench_20260902T145608Z/` gate 18).
- **`run_all` stress:** `reports/nightly-ot-bench_20260902T145737Z/` — gates **00–16 PASS** (`unset SKIP_PULL`, `WEATHER_SOAK_SECS=120`).
- **Synthetic-59:** target-pair soak **59/59 PASS** → `reports/wattlab-parity/artifacts/synthetic_59/`.
- **Gate 17:** `RUN_SYNTH59_HEALTH_MATRIX=1` — health matrix + overview analytics **PASS**.
- **BUILDING_100 parity:** `reports/railway-b100-parity_20260902T151009Z/` — FC1 **118.42 h**, runtime **1638.75 h**, series confirmed, `poll_seconds=300` (local ≡ Railway).
- **Harness:** `scripts/gates/railway_b100_parity_spot.sh` (B100 API capture + `summary.json`).
- **Deferred:** bldg2 Overview SPA browser sign-off; BUILDING_50 import + AFDD flood (no package on bench).
- Living docs: [`BUG_REPORT`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) · plan `.cursor/plans/3.3.19_remaining_bugs_stress.plan.md`.

## 2026-09-02 (midday) — 3.3.18 nightly refresh (post docker maintenance)

- **Docker maintenance** by operator; local stack restored via `openfdd_maint_update_resume.sh react-ot sha-ca67707 --skip-maintenance`.
- **Railway re-pin** already on `sha-ca67707`; backup `~/openfdd-backups/railway/20260902T120941Z/`.
- **bosspi fieldbus** re-pinned `sha-ca67707` arm64; Pipeline A **PASS** (`pi-1`/`bldg2` `has_telemetry:true`) after `railway redeploy` central+mqtt.
- **Nightly cycle 1:** `reports/nightly-ot-bench_20260902T123715Z/` — gate **00 GHCR pull PASS**; gate **01 FAIL** (fieldbus `health=starting` race); gates **02–16 PASS**.
- **Nightly cycle 2:** `reports/nightly-ot-bench_20260902T125016Z/` — gates **01–16 PASS** after harness fixes (`fix/nightly-harness-gates-01-18`).
- **Gate 18:** `reports/nightly-ot-bench_20260902T124850Z/` PASS (ingest_ok reset accepted when volume preserved).
- **BUILDING_100 Railway** FC1 AHU_1 **118.42 h** @ `sha-ca67707` — `reports/railway-f1-spot_20260902T124900Z/`.
- **Deferred:** bldg2 Overview UI; Railway F1 DF55/BUILDING_50/AFDD flood.
- Living docs: [`BUG_REPORT`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) · plan `.cursor/plans/3.3.18_nightly_refresh_ca67707.plan.md`.

## 2026-09-02 — 3.3.18 phase2 bench hygiene closeout

- **#821** merged — 3.3.17 `recreate_bench_fieldbus` in `00_pull` + `run_all` (fixes `fieldbus-poll-stale`).
- **#822** merged — 3.3.18 gate 03 ingest honesty (MQTTS + `ingest_ok>0` when counter stale).
- Container refresh: `openfdd_maint_update_resume.sh react-ot sha-3e35b2d`.
- **`run_all` PASS** — `reports/nightly-ot-bench_20260902T013750Z/` gates **01–16** (`WEATHER_SOAK_SECS=120`).
- GHCR publish pending on `0e5a9b16`; Railway re-pin deferred to `sha-0e5a9b1`.
- Living docs: [`BUG_REPORT`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) · plan `.cursor/plans/3.3.15_closeout_stress_9022f038.plan.md`.

## 2026-09-01 (late evening) — 3.3.16 closeout stress (post-GHCR)

- **GHCR + re-pin:** `sha-3e35b2d` / `3.3.16+3e35b2d45810` on Railway + local react; backup `~/openfdd-backups/railway/20260901T205611Z/`.
- **#817** merged on master (`3e35b2d4`) — #528, ruleLabels, gates 11–15.
- **Individual gates on `sha-3e35b2d`:** 01/06/08/10–15 **PASS**; 02/03 **PASS** after `fieldbus --force-recreate`; 16 **PASS** after e2e fix (`fix/gate16-playwright-rules-redirect`).
- **`run_all`:** `215607Z` — gates **01–15 PASS** on `sha-3e35b2d`; gate **16 FAIL** on tip master (e2e fix in PR #818).
- **#818+#819 merged** — gate 16 e2e fix + BUG_REPORT/SESSION_LOG closeout on tip `2201fe58`.
- **Deferred:** phase4 bldg2 Overview, phase6 Railway F1 remainder (DF55, BUILDING_50, AFDD flood).
- Living docs: [`BUG_REPORT`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) · plan `.cursor/plans/3.3.15_closeout_stress_9022f038.plan.md`.

## 2026-09-01 (evening) — Phase 7 patches in tree (pre-GHCR)

- **ruleLabels** — `frontend/web/src/lib/ruleLabels.ts`; sidebar/plots/reports use `ruleLabelStandard` / `ruleLabelPlotTitle` (no 36-char truncation).
- **#528** — `edge/src/fdd/registry_api.rs` STORAGE_URL-first parquet root; `fdd_rules::read_poll_from_cache` parent manifest walk (unit test PASS). Gate 06 still FAIL on running `sha-3c9f753` central until re-pin.
- **Gates re-run (individual, not full `run_all`):** 11 PASS (source fallback for reports wiring); 12 PASS; 14 PASS; 15 PASS (ledger IMPLEMENTED honesty for CAP-PLOTS/RCX); 06 FAIL poll_seconds only; 16 blocked host `libatk-1.0`.
- **BUILDING_100 Railway parity PASS** — artifact `reports/railway-b100-parity_20260901T190000Z/`.
- VERSION **3.3.16** in tree; stress `run_all` deferred until GHCR publish + re-pin.

## 2026-09-01 — 3.3.15 closeout + Phase 7 patch cycle (local stress)

- Product pin **`sha-3c9f753`** / `3.3.15+3c9f75311ae1` on Railway (central+mqtt+web) + local react; backup `~/openfdd-backups/railway/20260901T144551Z/`.
- Merged **#814** DataFusion 55 (`3c9f753`), **#815** BACnet→MQTT CI (`41af8523`), docs **#816** BUG_REPORT partial verdict (`6efd1f74`).
- Smoke **PASS**: `01_health_gates` 13/13; `10_react_spa` 24/24 (`sha-3c9f753`).
- Local `run_all` **PARTIAL FAIL** — `reports/nightly-ot-bench_20260901T144819Z/` (`SKIP_PULL=1`, `WEATHER_SOAK_SECS=120`): gates 01–05, 09–10, 13 PASS; **synthetic CSV FDD core PASS** (gate 06 FAIL = **#528** `poll_seconds` harness only).
- Phase 7 patch queue (log each in BUG_REPORT before fix): gate 08 weather mirror; gates 11–16 dashboard/parity/ledger/product-truth/Playwright. **Railway F1** (DF55, BUILDING_50, AFDD flood, bldg2) = separate tier — not local `run_all`.
- GH hygiene: 0 open PRs; 0 stale `feat/*`/`fix/*`; tip Actions green (optional BACnet `33529566569`).
- Living docs: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) Phase 7 table; plan `.cursor/plans/3.3.15_closeout_stress_9022f038.plan.md`.

## 2026-08-30 — Enhanced CSV/AFDD stress → 3.3.12

- Fixed `csv_flood_afdd_routine_sim` nested VAV equipment_id (leaf folder).
- Railway: BUILDING_50 import + 12h AFDD flood PASS; private lake bench package import + FDD/series PASS; MQTT `bldg2/pi-1` ingest advancing.
- Tip bump **3.3.12** (script + BUG_REPORT). Re-pin hub after Publish.


## 2026-08-30 — Patch cycle 3.3.11 CLOSEOUT (tip pin + dual pipeline)

- Tip `sha-91fb350` / `3.3.11+91fb3501aed2` on Railway (central+mqtt+web) + bosspi fieldbus arm64 + local react stack.
- Backup `~/openfdd-backups/railway/20260830T195849Z/` then re-pin; workspace historian intact; stream `edges:1` / `ingest_ok` advancing @ 60s.
- BUILDING_100 CSV import **HTTP 200** Railway + local; Railway FDD registry **ok** with `OPENFDD_PARQUET_ROOT=/workspace/openfdd`.
- Dual pipeline: bosspi→Railway exclusive; local GHCR pull react hub for firewall path. Soft-OPEN: SPA Overview browser confirm; live role_map; ≥1h parity soak; local full-B100 FDD latency.
- GH: tip Publish green; optional BACnet-MQTT failure not a product gate; 0 open product PRs at closeout start.

## 2026-08-30 — Patch cycle 3.3.11 START (UI P0 + MQTT≡CSV + tip pin)

- Hub still `3.3.9+2dce59a` while tip Publish `sha-7163be9` / VERSION→**3.3.11**.
- Product: nginx `client_max_body_size 128m` (CSV HTTP2); `normalize_role` aliases `zonetemp`→`zone_t`, `sa_t`/`duct_t`→`sat`.
- Ops: Railway backup script; bosspi weather device 599999 disabled; poll+publish 60s; fieldbus remains stopped until tip re-pin.
- Docs/skills: BUG_REPORT P0 IDs; railway-cli backup+always-pin-tip; package-mapping live MQTT; AGENTS 40–41.

## 2026-08-29 — Patch 3.3.10 (mqtt ACL on certs volume)

- Railway mqtt crash-looped: ephemeral `/mosquitto/config/acl` lost on restart.
- Move `acl_file` to `/mosquitto/certs/acl` (durable volume). Continue bosspi→Railway train.


## 2026-08-29 — Patch cycle 3.3.9 START (bosspi → Railway train)

- Continuous tiny-rev train until bosspi MQTTS → Railway hub stream healthy (plan `patch_cycle_3.3.9_railway_web_api`).
- Baseline: tip `sha-9667888` / 3.3.8; Railway web `/api` 404 (double-path); mqtt Crashed (no cert volume); bosspi fieldbus healthy on `sha-9667888` arm64.
- First bump: nginx `proxy_pass http://$openfdd_central;` + platform **3.3.9**; living BUG_REPORT; railway CLI skill + docs (Pi→Railway topology, GH tidy loop).


## 2026-08-29 — Patch cycle 3.3.8 CLOSED

- Tip `sha-9667888` / `3.3.8+96678888d875` on bensbench + bosspi **linux/arm64**.
- Product: `OPENFDD_STORAGE_URL` for package-ingest/analytics roots; bench `field_devices` auto-restore; Railway web nginx IPv6 resolver bracket (#797).
- Combined OT/synth **PASS**; cloud-sim **PASS**; dual MQTT 600s **PASS** (lab=bldg2=10 numeric, span≈540s); pcap FP scan **PASS**.
- UI smoke **PASS**: Actions during analytics; RCx economizer/runtime/mech-cool/bas-vs-web-oat; FDD series FC1 (5000 overlay hits); SPA routes.
- GH tidy: 0 open PRs, no stale `feat|fix` remotes; Publish GHCR **success**. Stack left running on `sha-9667888`.
- Railway: tip image ships resolver fix — operator re-pin hub to `sha-9667888` + `OPENFDD_NGINX_RESOLVER=auto` (CLI token not on host this cycle).
- Artifacts: `reports/patch338_20260829T152852Z/`.

## 2026-08-29 — Patch cycle start (3.3.8)

- BUG_REPORT blanked for patch cycle starting **3.3.8**.
- Scope: honor `OPENFDD_STORAGE_URL` in package-ingest + analytics `parquet_root` (coderabbit-storage); auto-restore bench `field_devices.toml` for OT soak hygiene; fix Railway `openfdd-web` nginx resolver IPv6 (`auto` → bracket `fd12::10`).

## 2026-08-29 — Patch cycle 3.3.7 CLOSED

- Tip `sha-3395551` / `3.3.7+33955515540e` on bensbench + bosspi **linux/arm64**.
- Product: bake `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60` into `07_cloud_sim` Pi override (#795) — closes gate10-pi-mqtt-interval.
- Combined OT/synth **PASS**; cloud-sim **PASS** (`mqtt_publish_interval=60`); dual MQTT 600s **PASS** (lab=bldg2=10 numeric, span≈540s, no hand-edit); pcap FP scan **PASS**.
- UI smoke **PASS**: Actions during analytics (no 401); RCx economizer green; FC1 series API ok.
- GH tidy: 0 open PRs, no stale `feat|fix` remotes. Stack left running on `sha-3395551`.
- Artifacts: `reports/patch337_20260829_020507/`.

## 2026-08-28 — Patch cycle start (3.3.7)

- BUG_REPORT blanked for patch cycle starting **3.3.7**.
- Scope: bake `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60` into `07_cloud_sim` Pi edge override (gate10-pi-mqtt-interval).

## 2026-08-28 — Patch cycle 3.3.6 CLOSED

- Tip `sha-aac593c` / `3.3.6+aac593c19833` on bensbench + bosspi **linux/arm64**.
- Combined OT/synth **PASS**; cloud-sim **PASS**; dual MQTT 600s **PASS** (after Pi `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60`); pcap FP scan **PASS**.
- UI smoke **PASS**: Actions during analytics (no 401); BUILDING_100 FC1 series 5000 rows; RCx economizer regression green.
- Closeout re-check: live MQTT peek lab+bldg2 numeric **PASS**; containers healthy; GH tidy (0 open PRs, no stale remotes).
- BUG_REPORT filled; stack left running on `sha-aac593c`.
- Artifacts: `reports/patch336_20260828_201214/` + `reports/patch336_live_205929/`.

## 2026-08-28 — Patch cycle start (3.3.6)

- BUG_REPORT blanked for patch cycle starting **3.3.6**.
- Scope: Overview→Actions 401 abort, BUILDING_100 FDD series building scope, mqtt-span `observed_at`, #763 bundle validate skeleton.

## 2026-08-27 — Patch cycle 3.3.5 CLOSED (dual MQTT + pcap)

- Tip `sha-fa83c72` / `3.3.5+fa83c7245942` on bensbench + bosspi **linux/arm64**.
- Combined OT/synth **PASS**; dual MQTT 600s **PASS** (lab+bldg2 telemetry, ingest growth); pcap FP scan **PASS** (ReadProperty-heavy, no Who-Is storm).
- BUG_REPORT filled; gate `11` uses privileged docker tcpdump + `bacnet capture --read --decode` when host lacks CAP_NET_RAW.
- Artifacts: `reports/patch335_validate_233516/`.

## 2026-08-27 — Patch cycle start (3.3.5)

- BUG_REPORT blanked for patch cycle starting **3.3.5**.
- Agent law: [`docs/RUST_LINT_HYGIENE.md`](docs/RUST_LINT_HYGIENE.md) (allow/expect elimination rules).

## 2026-08-27 — Plan 3 arm64 fieldbus CLOSED (bosspi native)

- bosspi: `openfdd-fieldbus:sha-fadf167` **linux/arm64** healthy (no qemu); OCI rev `fadf167ee984`.
- Gate `07` prefers native arm64 pull; amd64/qemu is fallback only.
- BUG_REPORT arm64 row **CLOSED**.

## 2026-08-27 — Plan 4 Feather retirement

- Deleted `feather_store` writers, central `OPENFDD_LEGACY_INGEST_MIRROR` dual-write, and product CLI `historian-migrate` / `historian-dry-run` / `historian-stats`.
- Compose central env: `OPENFDD_STORAGE_URL=file:///workspace/openfdd` (replaces `OPENFDD_PARQUET_ROOT` examples). Restore = same volume/S3 bucket across image updates.
- Nightly gate renamed `03_mqtt_parquet_persist.sh`; HISTORIAN_PROGRAM notes Feather retired / H6 not a product path.

## 2026-08-27 — Who-Is #526 CLOSED + BUG_REPORT tip `sha-6c2b89e`

- F3: `POST /bacnet/whois` sees **599999** + **600000** on tip (`#786`/`#787`).
- BUG_REPORT refreshed to `sha-6c2b89e`; historian H1–H9 Parquet / Plan 4 Feather delete; arm64 fieldbus = Plan 3 (multi-arch GHCR).
- Gate `07`: use `PI_SSH` for Pi IP (fix unbound `CLOUD_SIM_PI_SSH` under `set -u`).

## 2026-08-27 — Who-Is client #526 (discovery bind)

- Fieldbus Who-Is: `whois_bind_port = 0` auto-binds hosted `bacnet_server.port` on **`0.0.0.0`** with `SO_REUSEADDR` so directed-broadcast I-Am (remote Pi 600000 + LAN devices) is receivable; unicast `OPENFDD_FIELDBUS_BIND` is not used for discovery (misses broadcasts). Unicast reads stay ephemeral.
- Gate `07` F3 expects both instances in `POST /bacnet/whois`. Docs: root `AGENTS.md`, `services/fieldbus/AGENTS.md`, mcp INSTRUCTIONS.

## 2026-08-26 — Edge kit download + Railway agent auth (in flight)

- `POST /api/mqtt/edge-kits` + Operations MQTT **Download edge kit** (ZIP: public PEMs + `edge.json`, never CA key).
- Central auth: `OPENFDD_AGENT_PASSWORD` → username `agent` → operator JWT; admin `POST /api/auth/agent-token` for short-lived MCP tokens.
- Railway docs/checklist: dedicated agent secret, private MCP, no admin password in Cursor.

## 2026-08-26 — Ops MQTT UX closeout + Railway web DNS + 3.3.4 nightly

- PR #779: Ops MQTT/Sites, modeling docs, AFDD operator schedule Save, agent-spec sync.
- `openfdd-web`: lazy nginx upstream (`resolver` + `$openfdd_central`) for Railway private DNS race; `OPENFDD_NGINX_RESOLVER=auto`.
- Railway docs: deploy order central→mqtt→web; MQTTS hub default for live OT; checklist + `railway/` draft notes.
- Platform patch **3.3.4** for GHCR nightly refresh. Fieldbus Haystack Basic merged via #778.

## 2026-08-26 — Modeling docs + Ops/Sites UX agent-spec sync (#779)

- Product docs: `docs/modeling/{package-schema,heat-pump-buildings,rule-readiness}.md` + honesty gate on MCP package-mapping SCAFFOLD.
- SPA: Operations OT strip / MQTT console; Sites CSV|MQTT|Both **inventory** labels (not dual historian).
- Agent OS sync: `openfdd-package-mapping`, `openfdd-react-spa`, `DATA_CONTRACT`, bootstrap links in this folder’s `AGENTS.md`.
- No ingest/SQL/HP-1 contract code change. Fieldbus Niagara Basic is PR #778 (backend), not a data-contract change.
- HARD STOP: Vite approve before GHCR web for #779.

## 2026-08-18 — Overview tables, plant health matrices, RCx plots, revision pin

- Overview = DataTables + AHU/chiller/boiler/HP/VAV health matrices (`n/3`, unknown-not-PASS, red tint `--health-broken-*`). Plotly motor/mech/econ/BAS moved to additive RCx presets. CSV overlay is Inspect `/inspect`. Sidebar `GET /api/health` `3.3.1+shortsha`. Cargo **3.3.1**; PyPI stays **4.4.2**. Nightly stamps `version.json` + optional `:3.3.1-n<run>`.
- Agent docs: [`docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md); skill `openfdd-package-mapping`; MCP/INSTRUCTIONS/DATA_CONTRACT/VERSIONING updated. No vibe19 edits. No new MCP write tools.
- Vitest in `frontend/web`. Rust plant-health units on GHA. Do not claim dump 212→0 from this UX.

## 2026-08-16 — ECON mad_c ranking (#734) + dump-parity wave (#735) @ `sha-69494c2`

- Proof: not min-OA vs mad_c; blank-role `ex_dmpr_pos_fan_enable_pct` beat `mad_c` in ingest rank. OAT>63 enable~100 vs mad_c max 20 → SQL ECON-2 1422.92 h.
- #734: mad_c → oa_damper_pct; demote enable/min-OA; GHA competing-column fixture. Soak pin `sha-69494c2` health `3.3.0+69494c2195ac`: ECON-2 **0 h**, ECON-1 **327.08 h**; Synth **59/59**; analytics PASS.
- #735 + follow-on: diurnal/stats grain keys; rcx presets GET catalog; VAV `?/3` accept; zone-air-temp mean accept; ECON-1 ≤1 h accept. Dump blockers **449 → 212** (all remaining `fdd_findings`). No Windows prompt.

## 2026-08-16 — Fresh GHCR soak `sha-726211b` + B50 hourly append

- Pin `OPENFDD_IMAGE_TAG=sha-726211b` after `.env` (sticky `sha-8ab0b5e` otherwise). Health `3.3.0+726211b0d370`. vibe19 `:latest` `sha256:159802ca…` / 4.4.1 / `dump_tables` / agent_afdd rc 0.
- B50 IoT sim: seed hour-0 + 47 appends, replay `rows_added=0`. Synth **59/59** both sides; analytics PASS. Dump **449** blockers. ECON hours unchanged (pandas vs SQL mapping).
- No Windows playground prompt.

## 2026-08-16 — ECON CAST/`>= 1.5` (#731) soak `sha-5aebdfc`

- SQL: CAST damper/fan/OAT DOUBLE; percent if `>= 1.5`. GHA: damper 20 → ECON-2 0 h; fan-cmd 60 + damper 0 → ECON-1 > 0; fraction 0.55 still faults.
- GHCR `:nightly` = `sha-5aebdfc` digest `sha256:a56846e2…4006351a`. Pin `--no-pull`. Health `3.3.0+5aebdfc54434`.
- Synthetic-59 SQL **59/59**. B100 ECON hours **unchanged** (1422.92 / 0). AHU_1 parquet damper is Float64 0–100; when OAT>63 median is **100**, so 1422.92 h is frac-correct on this historian. Pandas 0 h / 326 h is a **point mapping** gap, not Utf8 CAST.
- Dump parity still **449** blockers. Mech OAT bins soak note committed with #731.

## 2026-08-15 — vibe19 4.4.1 + Synthetic-59 59/59 + B100 dump

- Playground PR #92: `open-fdd[reporting]==4.4.1`; diagnostic dump writes vav/mech/motor CSVs. bensbench pulled `ghcr.io/bbartling/vibe19:latest` (`sha256:101126ab…`).
- Synthetic-59: vibe19 and OpenFDD SQL **59/59**; analytics soak PASS. Synth ECON damper is 0–1.
- B100 dump-vs-dump on `sha-2c12c8e`: 449 blockers (vav_health rows now compared). ECON-1/2 still open on 0–100 damper; inline percent CASE in same SELECT as `FROM history`.
- Low-RAM: GHA/GHCR only; pin `sha-*` `--no-pull`. B100 dump-parity unpaused in AGENTS.md.

## 2026-08-14 — Metric boundary, slice CI, plot contracts, hourly append

- FDD SQL stays °F; `unit_system=metric` converts temperature roles at query; Lab sliders show °C.
- CI: `tests/fixtures/synthetic_slice` + `compare_synthetic_slice.py` + metric twin; plot JSON contracts; package append API + MCP `openfdd_csv_package_append`.
- Low-RAM: GHA publishes GHCR; no local stack compile.

## 2026-08-13 — Parity plots CI hardening (#715)

- Full-width Overview (Streamlit-like), A–Z Lab rule menu, named Plotly PNG stems.
- FDD series = required∪optional roles (SV/PID plots); PID-HUNT-1 rolling 1h TV/reversals.
- Mech OAT bins: status-before-amps + web/weather OAT; B100 notes in `docs/agent/B100_MECH_OAT_BINS_FIX.md`.
- `scripts/synthetic_59_overview_analytics_soak.py`; agent_spec laws 30–35.
- PR: https://github.com/bbartling/open-fdd/pull/715 — tip soak 59/59 after GHCR.

## 2026-08-12 — Overview expanders, session confirm overlay, SCHED-1 occupancy

- Overview plot Expanders default open (`OverviewPopulated`) so charts are not caret-hidden.
- FDD series overlay applies `session_config` `confirm_min`/params (`sql_detail_session`); Reports listens for `RULES_UPDATED`.
- SCHED-1 SQL + pandas `sched1`: portable occupancy (numeric 0/false + unoccupied tokens).
- Agent docs: root `AGENTS.md`, `CONTAINER_AGENT.md`, react/sql/ghcr skills — low-RAM GHCR-only refresh; synthetic-59 soak scripts; dump-parity paused.

## 2026-08-11 — open-fdd 4.3.0 library program

- Independent version API (`open_fdd.version.manifest`), effective catalog hashes, capability extras (`oracle` / `analytics` / `reporting`). `vibe19` extra deprecated until 5.0.
- Role-aware quality API; CHW-1 hydronic proof skip/off; SCHED-247 ranked proof (pressure inferred only).
- Structured evidence JSON; analytics package exports; wattlab_export copies shimmed.
- Parity inventory v2 (59/63) + golden fixtures for CHW-1 / SCHED-247. FC7 remains `concept_only`.
- Handoff: `docs/migration/open-fdd-4.3.0.md`, `docs/migration/VIBE19_OPENFDD_4.3_HANDOFF.md`.

## 2026-08-11 — Site lock, FDD/RCx vibe19 plots, Actions housekeeping

- SectionTabs + sidebar App pages keep `?site=` / `eq` (`hrefWithSession`). Overview + sidebar Active site are the only site editors; FDD / RCx / Results / WattLab show locked `zip:` caption (no Building select).
- FDD Plots: device type + status radios; inventory equipment (not results-only); auto-load series; missing `confirmed_fault` after a rule run is a failure. Overlay join hardened for `T` vs space / fractional seconds.
- RCx: `REQUIRED_RCX_PRESET_IDS` + `RCX_FAMILY_ORDER` (Zones first) + Heat pump/Weather placeholders; auto-run preset; companion donut/table/notes from envelope.
- Actions: default last 10; `DELETE /api/actions/:id` + `DELETE /api/actions`; JSONL cap 50.
- Overview radios after Equipment, left/horizontal, never inside `.oracle-hero`. Laws in `AGENTS.md` + `SITE_LOCK_FDD_RCX_CHECKLIST.md`. capabilities.yaml CAP-SITE / CAP-PLOTS / CAP-RCX match the matrix.

## 2026-08-10 — Sites tab + Run Rules removal + FDD/inspect

- Sites main tab after WattLab; Run Rules removed (`/rules` → Overview).
- Inspect equipment refetch; FDD Plots soft-show + building-scoped fault overlay; JWT default on react compose.

## 2026-08-07 — #683 RCx MOD fix + FDD parity Wave 0

- **#683** merged (`102049a`): DataFusion RCx timeseries downsample uses `%` instead of SQL `MOD()` (DF 43). GHCR pull-only on bensbench (no local docker build).
- **#684** Wave 0: generated `parity_inventory`, downgrade legacy `proven_building_100`/`ported_from_cookbook` → `sql_screening`/`concept_only`, fixture scaffold + seed oracle (`open_fdd.rules`), `docs/COOKBOOK_OWNERSHIP.md`, CI gates. Hard stop before Wave 1.


## 2026-08-07 — UX hard fixes wave (#677–#681)

- **#677** Dataset delete: sidebar + Data Model → `DELETE /api/datasets`; Actions kinds `dataset_delete` / `package_import`.
- **#678** Actions polish: structured detail (running pulse + metrics); selection-stable auto-refresh; log `analytics_rcx` / `analytics_fuel`.
- **#679** RCx span-preserving downsample + Plotly date axes; grey unmapped RCx/FDD Selects; FDD series `missing_roles` preflight.
- **#680** Reports artifacts/PDF removed (410 on `/api/reports*`); nav **FDD Plots** only.
- **#681** Metering = shared `FuelDashboard` + campus ZIP import (vibe20 Fuel via DF); smoke with `Buidling_100_50_fuel_use.zip`.
- GH hygiene: all five PRs merged to `master`, feature branches deleted, open PR list empty for this wave.

## 2026-08-07 — vibe19/vibe20 Plotly + UX parity (#675 wave)

- FDD Plots: `format_cell` RFC3339 timestamps (no PrimitiveArray dumps); stacked unit-family axes + fault bottom lane (vibe19 `rule_result_chart`); series overlays `confirmed_fault` from last rule results.
- Actions tab + durable `workspace/data/actions/log.jsonl`; Rules progress polls Actions (no fake 0%).
- Data Model role editors → Select from cookbook role catalog (`GET /api/fdd/cookbook-roles`).
- RCx preset coverage diagnostics UI; Metering Plotly (not JSON stub).
- Overview/tokens softened; Fuel Plotly 1:1 gaps (peer bullet, roll-12 EUI, ranked EUI, OLS fit/residuals, demand peaks).
- #674 Fuel Phase A merged `cc63574`; #675 Plotly/UX parity merged `d38d09b`.
- bensbench: `OPENFDD_IMAGE_TAG=sha-d38d09b` react-ot recreate; health `3.3.0+d38d09b`; Fuel EUI ~66.9 (7 query versions); BUILDING_100 economizer 4000 pts + RCx; Actions/cookbook-roles APIs live; fuel sidecar removed.

## 2026-08-07 — Vibe20 Fuel Phase A into Open-FDD (Rust + React)

- Added `services/central/src/fuel/` — campus.json + bill CSV ingest, Liberty Excel ZIP → embedded campus, analytics query_versions (summary/monthly/stacked/intensity/demand/quality/weather).
- React WattLab: Fuel ZIP upload + FuelDashboard Plotly tabs (Portfolio / Monthly / Weather / Demand / DQ).
- Twin/ECM remain Phase B/C stubs (E+ companion). Datasets: `liberty_campus_fuel.zip`, `Buidling_100_50_fuel_use.zip`.

## 2026-08-06 — DF parity, no-Python central image, docs refresh (#671)

- Merged `77cf8d7` — Overview economizer SQL + inspect flash; MAT/temps/BAS Plotly colors; RCx OAT scatter `ts_utc` alias; Liberty `web_*` inspect prefs.
- Central Dockerfile: debian-slim + Rust only; WattLab dump gated `OPENFDD_WATTLAB_PYTHON_EXPORT=1`.
- SPA overview-oracle client removed; ownership/README/docs present-tense React+DataFusion; CI checkers require React operator UI.
- #672 rustfmt fix for GHCR format check (`130b1f0`).
- GHCR Publish stack success on `130b1f0` (after #672 rustfmt); MCP dispatch also queued/published.
- bensbench: `OPENFDD_IMAGE_TAG=sha-130b1f0` react-ot recreate; `/api/health` `3.3.0+130b1f0`; generation=react; central has **no** python; economizer 4000 points; RCx OAT scatters (ahu/hw/chw) 2000 pts each.

## 2026-08-05 — Login page internet hygiene

- Removed bench credential path / `auth_required` dumps from `AuthPage`.
- Agent law: AGENTS.md + React skill — product UI treated as internet-facing;
  ops handoff only in docs/scripts, never SPA.

## 2026-08-04 — React delete + WattLab relocate (cutover)

- Relocated cookbook WattLab exporter → `tools/wattlab_export/`; central shells it (no `frontend/web`).
- Deleted `frontend/web` + `services/overview_oracle`; compose/CI assert React-only + ui absent.
- Stopped `openfdd-web` GHCR publish in stack + release workflows.
- Overview A/B: weekly plant bins, mech OAT bins, `/api/analytics/bas-vs-web-oat`.

## 2026-08-04 — Turnkey Rust cutover + agent_spec sync

- Locked product path: React + central DataFusion only; Overview via `/api/analytics/*` + client Plotly (no overview-oracle / React product).
- In progress on #663 tip: runtime weekly plant bins, mech OAT bins, BAS-vs-web route; React `centralOverview.ts` wiring.
- Updated `openfdd_agent_spec` (AGENTS/ARCHITECTURE/CONTAINER_AGENT/ownership/skills) so React is **cutover-delete**, not archived product UI.
- Plan: keep `openfdd_agent_spec/` current on every cutover PR (see turnkey plan `agent-spec` todo).
- Still pending: WattLab relocate → delete `frontend/web` + overview_oracle; stop `openfdd-web` GHCR; bensbench tip pull.

## 2026-08-02 — P1-M2-A ESLint + Playwright

- Real ESLint config (hooks/a11y/TS); CI fails on lint.
- Playwright e2e smoke suite (no network mocks); skips when SPA unreachable.
- Remaining Phase 1: M2-B/C, M3–M5 (see BUILD_CHECKPOINTS).
- Phase 2+ blocked: see `tools/open-fdd-vibe21-production/BLOCKERS.md` (oracle absent).

## 2026-08-02 — P1-G0 soak + P1-M1 openfdd-web GHCR

- P1-G0 soak: `reports/nightly-ot-bench_20260802T141626Z/` — gates **14/15 PASS**; suite FAIL on OT/SPA/MCP (honest).
- P1-M1: hardened `frontend/web` (npm ci, nginx-unprivileged :8080, CSP/cache headers, version.json); GHCR publishes `openfdd-web`; React SPA tagged archive-oracle.
- Smoke: `scripts/release/smoke_react_web_image.sh`.

Newest first. Append after non-trivial agent work.

---

## 2026-08-02 — P1-M0 Vibe 21 recovery foundation

- Landed `tools/open-fdd-vibe21-production/` as active Master Loop program kit.
- Added `docs/migration/react-rust/capabilities.yaml` + validator CI.
- Reconciled openfdd_agent_spec authority: modernization Phase 1+2 exit ≠ P1-G0.
- Nightly OT bench gates 14 (ledger) + 15 (product-truth honesty).
- **STOP** for human soak: `WEATHER_SOAK_SECS=120 WEATHER_SAMPLE_SECS=60 ./scripts/nightly-ot-bench/run_all.sh`
- Non-goals this PR: Unity ZIP picker, twin inference, container refresh, OT LAN 5007.

## 2026-08-01 — Phase 2 exit + Phase 3 readiness (agent_spec)

- Modernization Phase 1+2 exits approved; React sole product UI; DONE.
- Updated AGENTS/ARCHITECTURE/BUILD_CHECKPOINTS + `openfdd-react-spa` for post-P2 truth.
- Phase 3 (edge/live) remains outlook-only — `PHASE_3_READINESS.md`; no BACnet/MQTT work.
- Milestone A Phase 2/3 checkboxes unchanged (different program).

## 2026-07-31 — Agent skill bridge (Phase 1)

- Added `tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md` linking agent_spec ↔ modernization.
- Rewrote modernization `AGENTS.md` for Open-FDD (Rust/central; no FastAPI template).
- Added `openfdd_agent_spec/skills/openfdd-react-spa` wrapper + Cursor rule.
- Prompt 0 / AGENT_EXECUTION_SYSTEM require openfdd-react-spa before UI edits.
- BUILD_CHECKPOINTS Phase 1 status refreshed through M2 / M3 partial.

## 2026-07-31 — Phase 1 pause (M1 WIP on branch)

- M0 complete on master (#613/#614).
- Branch `feat/p1-m1-fixtures-oracle-baseline`: fixtures + exporter + interaction baseline (not merged).
- Resume: open/finish M1 PR → CI green → merge → continue M2–M6; keep GH tidy / CodeRabbit.

## 2026-07-31 — P1-M0-02 migration ledgers

- Seeded `docs/migration/react-rust/` capability / Python-exit / API / parity matrices from code.
- openfdd_agent_spec BUILD_CHECKPOINTS updated (M0 complete).

## 2026-07-31 — P1-M0-01 React/Rust modernization ADR

- Accepted ADR-001 (React+TS SPA → central Rust `/api`; DataFusion FDD; no FastAPI).
- Reconciled AGENTS / UI AGENTS / frontend README / architecture + web-app docs.
- Policy gate: `scripts/architecture_react_policy_check.py` (+ Stack Security Guards).
- Program kit committed under `tools/open-fdd-modernization/`.
- Ledgers path: `docs/migration/react-rust/` (matrices seeded in M0-02).

## 2026-07-30 — PyPI 4.2.0 publish fix (openpyxl)

- Core dep `openpyxl`; lazy honesty_export import so wheel smoke / bare install works.

## 2026-07-30 — PyPI ECM bugfix train (4.2.0)

- BUG-OFDD-ECM-007: toolkit modules `chiller_lockout` / `load_shed` / `schedule_align`.
- BUG-OFDD-ECM-009: `attach_twin_compare` + honesty workbook export (Contents…Measures/Demand).
- BUG-ECM-018: `MeasureHonestyStatus` FITTED/BALLPARK/NO_EP/FAIL_SIGN.
- Version bump **4.1.2 → 4.2.0**.

## 2026-07-30 — PyPI ECM bugfix train (4.1.2)

- BUG-OFDD-ECM-002: `save_as` same-path guard (no `SameFileError`).
- BUG-OFDD-ECM-003: `list_ecm_modules()` exported; docs vs `list_calculators()`.
- BUG-OFDD-ECM-012: expanded `FIELD_ALIASES` for DAT/SAT, ERV, occ, econ, schedules, …
- Version bump **4.1.1 → 4.1.2**; publish workflow assert updated.
- Tests: `test_job_save_same_path`, `test_list_ecm_modules`.

## 2026-07-30 — Twin dial AI context pointer (FDD → vibe20)

- Added `docs/mcp-agents/fdd-ops-to-twin-knobs.md` (pointer-only; no E+ ownership).
- Linked from mcp-agents index + companion WattLab/EnergyPlus (ops/reheat skills).
- Docs-only; G14 dial recipe lives in vibe20 `BUG_REPORT_TWIN_DIAL_AI_CONTEXT.md`.

## 2026-07-30 — Liberty soak turnkey closeout

- Merged open-fdd #601 → master `f904715` / GHCR `sha-f904715` (`f9047154dab631f0fecf81094bcc177c23c69712`).
- Playground #69 on develop `2323f28` (BUG-ECM-015 + ECM-ERV stub).
- Stack refreshed: csv + caddy (+ wattlab) on `sha-f904715` (API host :18080; Caddy :80).
- Health: `3.3.0+f9047154dab6`. Re-soak: Site UI 1-site; Delete…; economizer;
  Eng Findings 200; WattLab pages; Studio ss_*; MCP companion; no `d631e9c` pin.

## 2026-07-30 — Liberty soak turnkey (implementation)

- OFDD-070b CTE damper project; OFDD-076b `building_id`→`site_id`; Brand Open FDD;
  Sites Hive picker + Delete…; Jobs expander off default chrome; WattLab section +
  compose.wattlab / Caddy smoke; Eng Findings draft persist; OFDD-065 Liberty deltas;
  MCP companion + `openfdd_agent_context_pointers` + dual-site IT doc.
- Playground: BUG-ECM-015 + ECM-ERV-001 HAS_EP_PROTOTYPE stub (PR #69).

## 2026-07-30 — Liberty soak turnkey start (post-064eadb)

- Tip: open-fdd `064eadbc` / GHCR `sha-064eadb` · playground `4f3cdfd`.
- Phase 0: fetch/prune clean; no open PRs; csv stack + Caddy `:80` → UI,
  `/api/health` → `3.3.0+064eadbceda2` (central also on `:18080`).
- Campaign: OFDD-070b/076b, BUG-ECM-015, Brand, Sites/Jobs, WattLab V20,
  Findings, OFDD-065 deltas, MCP-CTX/IT, ERV P2, agent_spec sync.

## 2026-07-28 — Milestone B closeout (B6–B9)

- #585 merged: central `/api/jobs`, runs, stale, UI client.
- B6 findings/dispositions + WattLab handoff API; stale banner on job open.
- 14 UI + 7 central job tests; acceptance + closeout docs updated.

## 2026-07-28 — Milestone A closeout (B0)

- Added `docs/migration/MILESTONE_A_CLOSEOUT.md` and pandas UI inventory.
- `scripts/architecture_ownership_check.py` + cookbook-parity workflow hook.
- A closed with intentional residuals; Milestone B Jobs may proceed.

## 2026-07-28 — openfdd_agent_spec created

- Added `openfdd_agent_spec/` (orientation, Milestone A mission, architecture,
  ownership seed, skills, PR protocol, container protocol).
- Wired pointers from root `AGENTS.md`, `docs/agent/index.md`, migration audit.
- Docs-only; Milestone A Phases 0–4 code not executed in this pass.

## 2026-07-27 — twin retirement + GHCR refresh

- Playground #59: vibe19 runner/analytics → PyPI shims; pin `>=4.1.1`; vibe20
  workspace_tools `pick_best_twin_run` + `agent_build_ecm_packages`.
- open-fdd #580: `frontend/web` runner/analytics shims; React docs honesty.
- GHCR: vibe19/vibe20 `:develop` green; open-fdd stack `:nightly` matches
  `sha-f5207f6` (post-#580); MCP GHCR green.
- Prior: PyPI 4.1.0/4.1.1; playground #55–#58; open-fdd #578/#579; eight vibe20
  ECM twins delegated.

## 2026-07-28 — Milestone B Jobs (B1–B8 core)

- B1 job_store contract; B2 central /api/jobs; runs/stale/fingerprints; UI prefers central; findings + WattLab handoff helpers; closeout docs.

## 2026-07-30 — vibe freeze / open-fdd cutover

- **Freeze:** no further vibe19/vibe20 app tip features after today.
- **Product:** open-fdd GHCR UI (WattLab) + PyPI `open_fdd.ecm_engineering` + EnergyPlus-MCP companion.
- Docs: README cutover blurb; companion + FDD→Twin knobs rewritten off vibe Studio SoT.
- Golden ECM: `examples/liberty_dual_ahu/ECM_FULL_PARITY.xlsx` + `docs/ecm/OPENFDD_AGENT_ECM_HANDOFF.md`.
- PR: #607 (WattLab bake git + cutover docs + example).

