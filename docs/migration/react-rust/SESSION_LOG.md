# Session log — React / Rust modernization

Newest first.

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
