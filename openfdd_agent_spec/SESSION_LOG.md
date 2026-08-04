# Session log

## 2026-08-04 — Turnkey Rust cutover + agent_spec sync

- Locked product path: React + central DataFusion only; Overview via `/api/analytics/*` + client Plotly (no overview-oracle / Streamlit product).
- In progress on #663 tip: runtime weekly plant bins, mech OAT bins, BAS-vs-web route; React `centralOverview.ts` wiring.
- Updated `openfdd_agent_spec` (AGENTS/ARCHITECTURE/CONTAINER_AGENT/ownership/skills) so Streamlit is **cutover-delete**, not archived product UI.
- Plan: keep `openfdd_agent_spec/` current on every cutover PR (see turnkey plan `agent-spec` todo).
- Still pending: WattLab relocate → delete `services/ui` + overview_oracle; stop `openfdd-ui` GHCR; bensbench tip pull.

## 2026-08-02 — P1-M2-A ESLint + Playwright

- Real ESLint config (hooks/a11y/TS); CI fails on lint.
- Playwright e2e smoke suite (no network mocks); skips when SPA unreachable.
- Remaining Phase 1: M2-B/C, M3–M5 (see BUILD_CHECKPOINTS).
- Phase 2+ blocked: see `tools/open-fdd-vibe21-production/BLOCKERS.md` (oracle absent).

## 2026-08-02 — P1-G0 soak + P1-M1 openfdd-web GHCR

- P1-G0 soak: `reports/nightly-ot-bench_20260802T141626Z/` — gates **14/15 PASS**; suite FAIL on OT/SPA/MCP (honest).
- P1-M1: hardened `frontend/web` (npm ci, nginx-unprivileged :8080, CSP/cache headers, version.json); GHCR publishes `openfdd-web`; Streamlit UI tagged archive-oracle.
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

- Modernization Phase 1+2 exits approved; React sole product UI; Streamlit archived.
- Updated AGENTS/ARCHITECTURE/BUILD_CHECKPOINTS + `openfdd-streamlit-to-react` for post-P2 truth.
- Phase 3 (edge/live) remains outlook-only — `PHASE_3_READINESS.md`; no BACnet/MQTT work.
- Milestone A Phase 2/3 checkboxes unchanged (different program).

## 2026-07-31 — Agent skill bridge (Phase 1)

- Added `tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md` linking agent_spec ↔ modernization.
- Rewrote modernization `AGENTS.md` for Open-FDD (Rust/central; no FastAPI template).
- Added `openfdd_agent_spec/skills/openfdd-streamlit-to-react` wrapper + Cursor rule.
- Prompt 0 / AGENT_EXECUTION_SYSTEM require streamlit-to-react before UI edits.
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
- open-fdd #580: `services/ui` runner/analytics shims; Streamlit docs honesty.
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

