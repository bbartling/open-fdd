# Session log

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

