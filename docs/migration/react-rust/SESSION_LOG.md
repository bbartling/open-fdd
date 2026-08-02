# Session log — React / Rust modernization

Newest first.

## 2026-08-01 — Nightly OT bench GHCR tip-race recovery

- FAIL root cause (`reports/nightly-ot-bench_20260801T205013Z`): phase 00 pinned
  git tip `sha-37b8b43` before GHCR publish finished → cascade.
- Fix: wait/retry tip pull + nightly OCI revision fallback; abort suite on 00
  FAIL; fail-closed HTTP status helper (no `000000` false PASS).

## 2026-08-01 — Nightly OT bench modernized (react-ot)

- Committed `scripts/nightly-ot-bench/` for post–Phase-2: pull `sha-*`, assert
  nightly digests, `compose.react.yml` + `compose.react.fieldbus.yml`, React SPA
  gates (replaced Streamlit Lab). Writes opt-in via `BENCH_ALLOW_WRITES=1`.
- Stack recipe: `./scripts/openfdd_stack_up.sh react-ot`.

## 2026-08-01 — GHCR tip verify @ 61fee63

- Stack + MCP GHCR publishes success for tip; nightly↔sha digests recorded in PHASE_3_READINESS.
- compose.react.yml config smoke OK; openfdd-web GHCR absent (compose-build).
- Tip Actions all green; 0 open PRs after this pack → program tidy gate.

## 2026-08-01 — GHCR tip verify @ 9ef0411

- Stack + MCP GHCR publishes success; superseded by `61fee63` digest record.

## 2026-08-01 — Phase 3 readiness + skill compliance

- `PHASE_3_READINESS.md`: Phase 3 outlook-only; prerequisites MET/PARTIAL; skill matrix PASS.
- `openfdd_agent_spec` refreshed for React default / Phase 2 exit (Milestone A phases unchanged).
- Next: GHCR tip digest verify (same program).

## 2026-08-01 — P2 Prompt 8 final no-Python qualification

- `PHASE_2_QUALIFICATION.md` **PASS** at `47ae7b5` + this pack.
- React sole product UI; Streamlit archived; accepted risks listed. Phase 2 exit approved.

## 2026-08-01 — P2-M6 Streamlit product removal

- `STREAMLIT_PRODUCT_REMOVAL.md` + `services/ui/ARCHIVED.md`.
- Compose `ui` → `streamlit-legacy` profile; CI product gates → React.
- Next: P2 final no-Python qualification (Prompt 8).

## 2026-08-01 — P2-M5 fallback closeout

- `FALLBACK_CLOSEOUT.md`: fallback window closed; leaf deletes bundled into Prompt 7.
- Next: P2-M6 Streamlit product removal.

## 2026-08-01 — P2-M4-01 React production default flip

- `default_generation()` → React; `production_default_flipped=true`.
- `compose.react.yml` sets `OPENFDD_UI_GENERATION_DEFAULT=react`; `compose.central.yml` keeps streamlit for rollback.
- Routing/config only. Streamlit frozen for fallback until Prompt 7. Next: twin deletion (P2-M5).

## 2026-08-01 — P2-M3 canary decisions

- `CANARY_DECISIONS.md`: **PROMOTE** through 100% with Streamlit fallback.
- No routing change in this PR. Next: P2-M4 React default flip (turnkey auth).

## 2026-08-01 — P2-M2-01/02 shadow + soak

- Shadow harness `scripts/phase2_shadow_compare.py` + evidence under `evidence/shadow/`.
- Refreshed `tests/react_parity/manifest.json` hashes with documented algorithm; soak matrix in `SHADOW_SOAK.md` **PASS**.
- Next: P2-M3 canary promotion decisions.

## 2026-08-01 — P2-M1-01 computation closure ledger

- Added `COMPUTATION_CLOSURE.md` + `scripts/phase2_computation_policy_check.py` (wired in security.yml).
- React/central FDD + analytics callers CLOSED; metering historian rate→kWh PROVISIONAL; weather/ECM/site DEFER/ORACLE.
- Registry honesty: 24 PROVEN / 38 PROVISIONAL / 1 DISABLED. Human auth granted to continue Prompts 2–8 turnkey.
- Next: P2-M2 shadow/soak.

## 2026-07-31 — P2-M0-02 / P2-M0-03

- Migration telemetry counters + event ingest; rollback drill + schema expand-only note.
- Phase 2 M0 control plane complete. **Await human auth before Prompts 2–8.**

## 2026-07-31 — P2-M0-01

- Phase 1 exit verified (CUTOVER_LOG / PHASE_1_QUALIFICATION).
- Cutover control plane: `GET|PUT /api/ui/generation` with sticky cookie, header override, safe Streamlit default; audit JSONL; **production_default_flipped=false**.
- React `cutoverApi.ts`. Next: P2-M0-02 telemetry + P2-M0-03 rollback drill.

## 2026-07-31 — P1-M6-03

- Qualification pack: `PHASE_1_QUALIFICATION.md`
- Seeded `CUTOVER_LOG.md`: Phase 1 exit approved; Phase 2 not started.
- **Phase 1 exit gate closed** → next Phase 2 Prompt 0 / P2-M0-01.

## 2026-07-31 — P1-M6-02

- Added `docker/compose.react.yml`: mqtt + central + web (nginx SPA), **no** Streamlit `ui` service.
- SPA nginx proxies `/api` → central; `OPENFDD_REACT_UI=1` on central.
- Documented in `NO_PYTHON_STACK.md`; CI compose config loop includes compose.react.yml.
- Next: P1-M6-03 qualification pack + CUTOVER_LOG.

## 2026-07-31 — P1-M6-01

- Closed `PYTHON_EXIT_MATRIX.md`: zero UNKNOWN / zero BLOCKED dispositions.
- Enumerated Phase 2 deletion candidates in `PHASE_2_DELETION_CANDIDATES.md` (not executed).
- Next: P1-M6-02 no-Python compose profile.

## 2026-07-31 — P1-M5-F

- Thin `AuthPage` + `authApi` for `/api/auth/status|me|login`; Bearer token in sessionStorage; `apiFetch` attaches Authorization.
- Next: P1-M6-01 Python exit matrix closure.

## 2026-07-31 — P1-M5-E

- ReportsPage: plots + Artifacts mode (`/api/reports` list/draft/engineering-findings). PDF/DOCX noted ORACLE.
- WattLabPage: `POST /api/jobs/{id}/wattlab/handoffs` with portable_zip_uri.
- Next: P1-M5-F thin AuthPage.

## 2026-07-31 — P1-M5-D

- FindingsPage now uses job `/api/jobs/{id}/findings|dispositions` (not FDD results).
- `findingsApi.ts`: get/put + disposition upsert by `correlation_key`.
- FDD registry results remain on RulesPage. Next: P1-M5-E reports + WattLab handoff.

## 2026-07-31 — P1-M5-C

- Typed `analyticsApi.ts`: metering / RCx / runtime POST clients + `listFddEquipment` + `monthlySumClient` parity helper.
- `MeteringPage`: inline `{period,kwh}` → `/api/analytics/metering`, client↔API parity metric, RCx AHU stub.
- `HomePage` Overview: contract + equipment inventory table (widget gallery collapsed).
- Next: P1-M5-D findings/dispositions.

## 2026-07-31 — P1-M5-B

- FDD plot datasets: `plotDataset.ts` builds figure JSON from `/api/fdd/series`; `ReportsPage` loads building/eq/rule and renders SVG PlotlyHost + preview table.
- PlotlyHost now accepts figure traces (no plotly npm yet). Missing-segment counts for parity notes.
- Next: P1-M5-C analytics/metering.

## 2026-07-31 — P1-M5-A

- Enriched `GET /api/fdd/rules` summaries (aliases, optional_roles).
- RulesPage tuning panel: `GET /api/fdd/rules/{id}/params` → Slider + numeric entry; clamp to registry bounds; save via session-config `params`; bind into `/api/fdd/run`.
- Next: P1-M5-B plot datasets.

## 2026-07-31 — P1-M4-04

- React `RulesPage` → `POST /api/fdd/run` (registry mode, AbortSignal cancel); `FindingsPage` → `GET /api/fdd/results` with equipment/status filters + JSON/CSV download.
- Typed `fddApi.ts` (status/rules/run/results/series helpers). Run is synchronous (central `spawn_blocking`); UI shows progress + cancel via fetch abort.
- No Python in React FDD path — DataFusion only. Compose no-Python profile remains M6-02.
- Next: M5 family A (rule catalog/tuning depth) or M6 exit wave after M4 gate.

## 2026-07-31 — P1-M4-03

- Added `GET /api/csv/import/package/mapping` + `/buildings` inventory (columns, unmapped/ambiguous, VAV parent AHU heuristic, sampling health, blockers vs warnings).
- React `MappingPage` + `mappingApi.ts`: edit column→role, save via `POST …/package/roles` + revisioned `PUT /api/fdd/session-config`, download mapping manifest JSON.
- Blank roles stay blank (no guessed fills). Next: P1-M4-04 run/results/download.

## 2026-07-31 — P1-M4-02

- Extended Rust `openfdd_package_v1` ingest defenses in `edge/src/csv_ingest/package.rs` (traversal, absolute paths, symlinks, zip-bomb ratio, case collisions, size caps).
- Hostile archive unit tests mirror `tests/react_parity/fixtures/hostile_zip/cases.json` (generated at test time).
- React `UploadPage` + `uploadApi.ts` multipart client → `POST /api/csv/import/package`; dataset id = `building_id`.
- `?job=` session selection display-only — package import API has no job association yet (noted in CAP-UPLOAD / DECISIONS).
- Next: P1-M4-03 mapping/validation UI.

## 2026-07-31 — P1-M4-01

- Typed `frontend/web/src/api/jobsApi.ts` for list/get/create/patch/archive/restore/duplicate against existing `/api/jobs*`.
- `JobsPage` CRUD UI with archived toggle, URL-backed `?job=` selection, `meta_revision` patch conflicts, archive/restore/duplicate.
- Vitest: `jobsApi.test.ts` + `JobsPage.test.tsx` (mocked API). Next: P1-M4-02 upload slice.

## 2026-07-31 — P1-M3-03

- URL session translation (`?job=`, `?eq=`, `?site=`, `?wl=`, `?section=`) + form drafts in sessionStorage.
- `useSessionQuery`, dirty-form unload warning; Jobs/WattLab/Mapping wired.
- `SESSION_TRANSLATION.md` + deep-link tests. M3 shell gate → next M4-01 Jobs CRUD.

## 2026-07-31 — docs: agent skill bridge

- Wired `openfdd_agent_spec` + streamlit-to-react skills into Phase 1 bootstrap
  (`AGENT_SKILL_BRIDGE.md`, Cursor rule, Prompt 0).
- Next: P1-M3-03 routing/session then M4 slice.

## 2026-07-31 — P1-M3-02

- Accessible widget primitives under `frontend/web/src/components/widgets/` (select, slider, checkbox/radio/toggle, file upload, buttons, tabs, expander, metric, table, progress/badge, Plotly host placeholder, confirm modal, toast/inline alert).
- `widgets.css` token-driven styles; barrel `index.ts`; vitest coverage for select, slider keyboard, checkbox, modal, expander.
- Home widget gallery demo on HomePage. Next: P1-M3-03 routing/session.

## 2026-07-31 — P1-M3-01

- Expanded design tokens + Streamlit-like shell geometry (`LAYOUT_GEOMETRY.md`).
- Collapsible sidebar, title/caption, horizontal section tabs (REQUIRED_MAIN_SECTIONS order).
- Alert + skeleton/spinner styles; AppShell component tests.
- Next: P1-M3-02 widget primitives.

## 2026-07-31 — P1-M2-03

- Documented async poll contract (`ASYNC_OPS.md`) aligned with jobs run statuses.
- Added `frontend/web/src/api/asyncOps.ts` + vitest coverage.
- M2 platform gate closed → next P1-M3 shell parity.

## 2026-07-31 — P1-M2-02

- Scaffold `frontend/web` Vite+React+TS SPA (routes, API client, contract types, Docker).
- CI job `React web (frontend/web)` in rust-ci.yml.
- Next: P1-M2-03 async ops substrate.

## 2026-07-31 — P1-M2-01

- Added `services/central/src/contract.rs`: error envelope, request-id middleware, contract metadata.
- `GET /api/capabilities` now includes `contract.*` + `react_ui` flag (`OPENFDD_REACT_UI=1`).
- Doc: `CONTRACT_CONVENTIONS.md`.
- Next: P1-M2-02 React project shell.

## 2026-07-31 — P1-M1 gate (PR #615)

- Fixture catalog + content hashes under `tests/react_parity/`.
- Oracle exporter `tools/react_parity/export_reference_json.py` (byte-stable ×3).
- Interaction baseline: all CAP-* rows marked NONVISUAL (M3 visual) — honest M1 gate.
- Next: P1-M2-01 contract conventions.

## 2026-07-31 — P1-M0-02

- Seeded CAPABILITY_MATRIX, PYTHON_EXIT_MATRIX, API_CONTRACT_MATRIX, PARITY_EVIDENCE from code inventory.
- 16 capability rows; 64 production UI modules + streamlit entry; central `/api` families listed.
- Dispositions remain UNKNOWN pending M1 characterization.

## 2026-07-31 — P1-M0-01

- ADR-001 accepted; instruction hierarchy reconciled; policy CI wired.
- Next: P1-M0-02 capability / Python-exit / API ledgers from code inventory.
