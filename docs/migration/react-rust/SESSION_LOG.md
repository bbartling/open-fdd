# Session log — React / Rust modernization

Newest first.

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
