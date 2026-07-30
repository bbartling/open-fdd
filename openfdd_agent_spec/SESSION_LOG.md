# Session log

Newest first. Append after non-trivial agent work.

---

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

