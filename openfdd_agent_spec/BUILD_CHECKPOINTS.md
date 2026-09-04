# Milestone A — build checkpoints

Track durable progress. Update whenever Milestone A status changes (merge,
blocker, or intentional exception). Detail:
[`MILESTONE_A.md`](MILESTONE_A.md),
[`docs/MIGRATION_MATRIX.md`](docs/MIGRATION_MATRIX.md),
[`docs/migration/MILESTONE_A_CLOSEOUT.md`](../docs/migration/MILESTONE_A_CLOSEOUT.md).

Legend: `[x]` done · `[~]` partial / residual · `[ ]` remaining

**Product truth (2026-08-06):** React SPA + DataFusion central (no Python in
product image/request path). Overview/RCx/FDD analytics via `/api/analytics/*` +
`/api/fdd/*`. PyPI `open_fdd` + dual cookbooks remain for third-party/oracle use.
SPA skill: [`skills/openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md).

**Closeout status (2026-07-28):** Milestone A **closed with intentional residuals**
(see closeout doc). Milestone B Jobs may proceed.

---

## Phase 0 — Architecture freeze

- [x] Human architecture locks ([`ARCHITECTURE.md`](ARCHITECTURE.md))
- [x] Machine-readable seed ([`ownership.yaml`](ownership.yaml))
- [x] CI: ownership schema + cookbook path smoke (`scripts/architecture_ownership_check.py`)
- [~] Broader forbidden-import / terminology suites — residual harden
- [x] Required cookbook paths protected via ownership check + cookbook parity

## Phase 1 — Packaging / release / containers

- [x] PyPI `open-fdd` 4.1.0 / 4.1.1
- [x] vibe19 / UI pins `>=4.1.1,<5`
- [~] Version policy docs; generated manifest residual
- [~] Image metadata / nightly channel OK; deeper in-container asserts residual
- [x] Stack + MCP GHCR green post twin retirement

## Phase 2 — Shared contracts + rule manifest

- [ ] `open_fdd.contracts` — **deferred residual**
- [ ] Canonical rule manifest — **deferred residual**
- [~] Cookbook ↔ registry agreement via existing cookbook-parity

## Phase 3 — Vibe 19 thin-oracle cutover

- [x] Rules shims + runner/analytics package rebinds
- [x] Custom rules KEEP intentional
- [~] Full KEEP/SHIM/MOVE/DELETE matrix residual

## Phase 4 — Vibe 20 generic ECM migration

- [x] Eight twins delegated
- [~] Remaining keepers — residual / parallel track
- [x] Docker-socket runner = documented follow-on (not A blocker)

## Cross-cutting

- [x] Dual cookbooks present
- [x] Cookbook parity CI
- [x] Closeout audit committed
- [ ] Playground GHCR retirement — out of A

---

# Milestone B — Jobs / provenance (2026-07-28)

**Closeout status:** Milestone B **complete** (central SoT + UI thin client; see
[`MILESTONE_B_CLOSEOUT.md`](../docs/migration/MILESTONE_B_CLOSEOUT.md)).

- [x] B0 — Milestone A closeout audit (#583)
- [x] B1 — Job filesystem contract (#584)
- [x] B2 — Central `/api/jobs` filesystem store (#585)
- [x] B3 — Dataset refs + canonical fingerprint
- [x] B4 — Run records + statuses
- [x] B5 — Stale engine (`/stale`)
- [x] B6 — Findings + dispositions schemas + API
- [x] B7 — React Jobs on central API + stale banner
- [x] B8 — WattLab handoff manifest (job-native)
- [x] B9 — Acceptance doc + GHCR publish on merge

---

# Milestone C — DataFusion analytics cutover (2026-07-28)

**Status:** **Partial** on branch `milestone-c/c1-c2-analytics-runtime`.
Engine label: `central-analytics-v1` (DF SQL MemTable follow-up).
Docs: [`MILESTONE_C_CLOSEOUT.md`](../docs/migration/MILESTONE_C_CLOSEOUT.md),
[`MILESTONE_C_ACCEPTANCE.md`](../docs/migration/MILESTONE_C_ACCEPTANCE.md),
[`MILESTONE_C_ANALYTICS_MATRIX.md`](../docs/migration/MILESTONE_C_ANALYTICS_MATRIX.md),
[`MILESTONE_C_RULE_PARITY.md`](../docs/migration/MILESTONE_C_RULE_PARITY.md),
[`MILESTONE_C_ANALYTICS.md`](../docs/benchmarks/MILESTONE_C_ANALYTICS.md).

- [x] C0 — B adversarial verification + README / cookbook honesty
- [x] C1 — Analytics envelope + `/api/analytics/*` contracts
- [x] C2 — Runtime Δt compute + economizer diagnostics (live)
- [~] C3 — Sensor health minimal compute (coverage / flatline / stats)
- [~] C4 — Schedule occupied + after-hours fan hours (minimal)
- [~] C5 — Mechanical cooling evidence hierarchy (minimal; OAT bins residual)
- [~] C6 — Economizer live; RCx AHU coverage stub; full RCx UI residual
- [~] C7 — VAV comfort ranking minimal; full VAV RCx residual
- [ ] C8 — Plant evidence (chiller/boiler) — not started
- [~] C9 — Metering monthly kWh sum (minimal)
- [~] C10 — Rule parity fixture notes + mutation checklist (harness residual)
- [ ] C11 — Retire production pandas paths; filled benchmarks; `sha-*` acceptance

---

# Milestone D — Gaps bridge + WattLab / E+ (2026-07-28)

**Status:** **Partial** on branch `milestone-d/d1-historian-datafusion-runtime`.
Docs: [`MILESTONE_D_CLOSEOUT.md`](../docs/migration/MILESTONE_D_CLOSEOUT.md),
[`MILESTONE_D_ACCEPTANCE.md`](../docs/migration/MILESTONE_D_ACCEPTANCE.md),
[`MILESTONE_D_RULE_PARITY.md`](../docs/migration/MILESTONE_D_RULE_PARITY.md),
[`MILESTONE_D_GAP_REGISTER.md`](../docs/migration/MILESTONE_D_GAP_REGISTER.md).

- [x] D1 — Historian DataFusion bridge for runtime analytics
- [x] D2 — SQL rule parity mutation path check + CI + BUILDING_100 note
- [x] D3 — Job-native WattLab handoff UI (zip additive)
- [x] D4 — Restricted E+ runner policy + QUEUED persist stub (no in-process E+)
- [x] D5 — Vite `:5173` hint scrub + closeout / acceptance / gap register
- [ ] D4b — External runner claim loop + full artifact attach UX
- [ ] D2b — Logical gate mutations + `PROVEN_MULTI_BUILDING`
- [ ] D5z — Full-stack `sha-*` soak

---

# Liberty soak turnkey (2026-07-30) — post-064eadb

**Status:** open-fdd #601 **merged** (`f904715` / `sha-f904715`) · playground #69 **merged** (`2323f28`).

- [x] Phase 0 — GH tidy + csv+caddy on `sha-064eadb`
- [x] OFDD-070b economizer CTE + OFDD-076b `building_id`→`site_id`
- [x] BUG-ECM-015 rows/`annual_usd` (playground)
- [x] OFDD-UI-BRAND + OFDD-MCP-CTX companion docs + pointers tool
- [x] OFDD-UI-SITE / JOBS (Hive picker, Delete…, Jobs expander off default)
- [x] OFDD-UI-V20 WattLab section + compose.wattlab + Caddy smoke
- [x] OFDD-069 findings draft persist + OFDD-065 Liberty deltas + MCP-IT doc
- [x] ECM-ERV-001 HAS_EP_PROTOTYPE residual stub (not product cascade)
- [x] Merge #601 → GHCR `:sha-<final>` + `:nightly` → re-soak checklist

---

# React / Rust modernization — Phase 1+2 (2026-07-31 → 2026-08-01)

Program: [`tools/open-fdd-modernization/`](../tools/open-fdd-modernization/README.md) ·
Skill bridge: [`AGENT_SKILL_BRIDGE.md`](../tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md) ·
React SPA skill: [`openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`](../tools/open-fdd-modernization/openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md ·
Ledgers: [`docs/migration/react-rust/`](../docs/migration/react-rust/README.md) ·
ADR: [`ADR-001`](../docs/architecture/adr-001-react-rust-modernization.md)

Agents **must** follow `openfdd_agent_spec` + openfdd-react-spa skills for UI PRs
(see Cursor rule `.cursor/rules/openfdd-phase1-react-parity.mdc`).

### Phase 1

- [x] P1-M0-01 — ADR + instruction reconciliation + policy CI
- [x] P1-M0-02 — Capability / Python-exit / API ledgers
- [x] P1-M1 — Fixtures / oracle exporter / React baseline (#615)
- [x] P1-M2 — Rust contracts + React shell + async ops (#616–#618)
- [x] P1-M3 — Parity shell / widgets / navigation (#619+)
- [x] P1-M4 — Jobs/CSV/map/run vertical slice
- [x] P1-M5 — Domain families (A–F) + Auth thin slice
- [x] P1-M6 — No-Python RC qualification (exit approved)
- [x] Agent skill bridge — `AGENT_SKILL_BRIDGE.md` + `openfdd-react-spa` skill + Cursor rule

### Phase 2

- [x] P2-M0 — Cutover control plane + telemetry + rollback (#636–#637)
- [x] P2-M1 — Computation closure ledger + policy (#638)
- [x] P2-M2 — Shadow/soak (#639)
- [x] P2-M3 — Canary PROMOTE (#640)
- [x] P2-M4 — React production default flip (#641)
- [x] P2-M5 — Fallback closeout (#642)
- [x] P2-M6 — React product path removal (#643)
- [x] Prompt 8 — Final no-Python qualification PASS (#644)

### Phase 3 (modernization edge/live) — outlook only

- [ ] P3-M0+ — **Not started** (see `PHASE_3_READINESS.md`). Distinct from Milestone A Phase 3 (vibe19 oracle) above.
---

# Vibe 21 production recovery — P1-M0 (2026-08-02)

Program: [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/README.md) ·
Master Loop: [`prompts/MASTER_PRODUCTION_LOOP.md`](../tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md) ·
Ledger: [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml)

Modernization Phase 1+2 “exit” above is **architecture direction**. This section
tracks the recovery program evidence gates.

- [x] P1-M0-A — `capabilities.yaml` + `scripts/validate_capabilities_ledger.py` + CI
- [x] P1-M0-B — openfdd_agent_spec / AGENTS authority reconciliation
- [x] Nightly honesty gates 14–15 (ledger + product-truth greps)
- [x] P1-G0 soak — `reports/nightly-ot-bench_20260802T141626Z/` (14/15 PASS; OT LAN honest FAIL)
- [x] P1-M1-A/B — hardened `openfdd-web` Dockerfile + GHCR publish in stack workflow
- [x] P1-M1-C — `scripts/release/smoke_react_web_image.sh` (no-Python inspect)
- [x] P1-M2-A — ESLint (real) + Playwright real-stack smoke harness (self-skip if SPA down)
- [ ] P1-M2-B — unified error/loading/recovery matrix
- [ ] P1-M2-C — accessibility/responsive shell (axe/keyboard)
- [x] P1-M3 partial — Playwright product markers (Overview/Auth/Jobs/…/WattLab) + nightly gate 16; PlotlyHost/demo strip still open
- [ ] **3.3.15 Phase 7** — local `run_all` PARTIAL (`20260901T144819Z`): gates 08, 11–16 open; synthetic CSV FDD core PASS; #528 harness-only — see BUG_REPORT Phase 7 table
- [ ] P1-M3-* — PlotlyHost replacement; remove demo/stub product controls; full browser-qualify workflows
- [ ] P1-M4-* — SQL oracle closure by family; RCx/metering real algorithms; report no-Python
- [ ] P1-M5-* — independent qualification pack + React retirement guard

---

# Turnkey Rust cutover (2026-08-04)

Product voice = React + DataFusion only. Track deletion / GHCR / agent_spec honesty.

- [x] Overview analytics path = central `/api/analytics/*` + client Plotly (no overview-oracle product call)
- [x] Runtime weekly plant bins (`runtime-weekly-v1`) + React plant charts
- [x] Mech OAT bins on `/api/analytics/mechanical-cooling` + React
- [x] BAS vs web OAT (`/api/analytics/bas-vs-web-oat`) + React
- [x] Relocate WattLab exporter off `frontend/web` → `tools/wattlab_export/`
- [x] Delete `frontend/web` + `services/overview_oracle`; scrub CI/docs/compose
- [x] Stop publishing `openfdd-web` to GHCR (workflow scrub; tip images after master merge)
- [x] `openfdd_agent_spec/` updated for cutover direction (keep in sync every PR)
- [x] #671 DF Overview/RCx color+OAT parity; Rust-only central; present-tense docs (+ #672 rustfmt)
- [x] bensbench tip `sha-130b1f0` pull + react-ot smoke (BUILDING_100 economizer + RCx OAT scatters; no Python in central)- [x] #674 vibe20 Fuel Phase A (Rust campus/bills analytics + React FuelDashboard) merged `cc63574`
- [x] vibe19/vibe20 Plotly/UX parity: FDD stacked axes + timestamps, Actions log, Data Model role Select, RCx coverage, Metering Plotly, theme soften, Fuel chart 1:1 gaps

---

# Historian / Railway program checkpoint (2026-08-21)

- [x] P1-M7-00 — H1/H2 merged; H3 DataFusion historian registration/query-safety merged via #758 (`c5974abd`)
- [x] P1-M7-01 — H4 bounded offline local historian compaction merged via #760 (`32eabc68`) after exact-head CI + review passed
- [x] P1-M7-02 — H5 generic S3/object-store + DataFusion tuning + central scoped runtime/Railway/loopback-MinIO merged via #762 (`9239574a`); canonical S3 bucket remains private and container disk is scratch/spill
- [~] P1-M7-03 — H6 migration/operator tooling active via #764: trusted Parquet/JSONL/Arrow discovery + bounded restart-safe conversion, preservation receipts/reports, footer-only canonical stats, operator CLI, fail-closed S3 compatibility scope
- [ ] P1-M7-04 — H7 live-ingest micro-batch cutover: trustworthy equipment/role identity, H2 accumulator wiring, elapsed/shutdown flush, persisted latest timestamp, retire durability-critical JSONL/IPC rewrite

---

# Ops train 3.3.20 (2026-09-03)

Product ship vs stress closeout — living detail: [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) · [`docs/operations/STRESS_CLOSEOUT.md`](../docs/operations/STRESS_CLOSEOUT.md).

- [x] Engineering export + utilities foundation — #827 `15baccf8` / pin `sha-15baccf` / VERSION **3.3.19**; #828 gate-19 shell
- [x] Agent handbooks — `LOCAL_DEPLOYMENT.md`, `STRESS_CLOSEOUT.md`, skill `openfdd-stress-closeout` (#829)
- [x] 3.3.20 rigorous stress LAST — Railway backup `20260903T175358Z` + hub/local/bosspi `sha-0c1029d`; `run_all` 00–16; synth59 59/59; gate 17; B100; Creekside full; gate 19 READY; ZAP baseline (no High/Critical)
- [ ] capabilities.yaml — **not** an ops-stress ledger; leave product-capability rows unchanged for this train

# Ops train 3.3.20 platform (x86 → Railway, 2026-09-04)

- [x] VERSION **3.3.20** + Railway-hub stress harness — #831 `aef6fc1f` / `sha-aef6fc1`
- [x] Field cutover: react-ot + bosspi off closeout; `openfdd_fieldbus_railway_up.sh sha-aef6fc1`; hosted-weather loopback
- [x] `run_railway_hub_stress.sh` + BUG_REPORT verdict CLOSED (CSV + ZAP)
