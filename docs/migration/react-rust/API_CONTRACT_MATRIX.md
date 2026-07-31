# API contract matrix (P1-M0-02 seed)

Source: `services/central/src/routes.rs` at inventory time. Versioning/`/api/v1` policy lands in P1-M2-01.

| route family | methods (see OpenAPI) | owner | React consumer target | contract status | notes |
|---|---|---|---|---|---|
| `/api/agent` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/agent/tools |
| `/api/analytics` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/analytics/economizer, /api/analytics/mechanical-cooling, /api/analytics/metering, /api/analytics/rcx/ahu (+6) |
| `/api/auth` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/auth/login, /api/auth/me, /api/auth/status |
| `/api/building` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/building/snapshot |
| `/api/capabilities` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/capabilities |
| `/api/commands` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/commands, /api/commands/{command_id}/ack |
| `/api/csv` | see OpenAPI | central | Phase 1 React | EXISTS | package mapping: GET /api/csv/import/package/mapping, /buildings; POST /package, /package/roles; + plan/execute/preview |
| `/api/data-management` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/data-management/summary |
| `/api/datasets` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/datasets, /api/datasets/{dataset_id}/preview |
| `/api/edges` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/edges, /api/edges/{edge_id}, /api/edges/{edge_id}/discovery, /api/edges/{edge_id}/metadata |
| `/api/export` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/export/meta |
| `/api/faults` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/faults/status, /api/faults/summary |
| `/api/fdd` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/fdd/cache/status, /api/fdd/equipment, /api/fdd/results, /api/fdd/roles (+6) |
| `/api/fdd-rules` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/fdd-rules |
| `/api/fdd-schema` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/fdd-schema/tables |
| `/api/health` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/health, /api/health/stack |
| `/api/host` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/host/stats |
| `/api/ingest` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/ingest/stats |
| `/api/jobs` | see OpenAPI | central | Phase 1 React | EXISTS | React consumer: `jobsApi.ts` + JobsPage (M4-01 list/create/patch/archive/restore/duplicate; revision conflict on PATCH) |
| `/api/reports` | see OpenAPI | central | Phase 1 React | EXISTS | e.g. /api/reports, /api/reports/draft, /api/reports/engineering-findings, /api/reports/templates (+3) |

## Gaps for React (P1-M2+)

| gap | needed by | status |
|---|---|---|
| Unified error envelope + request IDs | all screens | **DONE (M2-01)** — `contract.rs` + `CONTRACT_CONVENTIONS.md`; middleware echoes `x-request-id` |
| Contract version on `/api/capabilities` | SPA bootstrap | **DONE (M2-01)** — `contract.contract_version` |
| Async operation poll/cancel substrate | FDD run, import, reports | **DONE (M2-03)** — `ASYNC_OPS.md` + `frontend/web/src/api/asyncOps.ts` poll helper |
| Typed TS client generation | SPA | **PARTIAL (M4-02)** — jobs + upload clients (`jobsApi.ts`, `uploadApi.ts`) |
| Package upload streaming defenses in Rust | CAP-UPLOAD | **DONE (M4-02)** — `edge/csv_ingest/package.rs` hostile suite + `uploadApi.ts` multipart client |
| Plot dataset contracts (not chart HTML) | CAP-PLOTS | NOT_STARTED (M5-B) |
