# Phase 3 readiness + skill compliance

**Date:** 2026-08-01  
**Modernization tip:** `7ba35fc` (Phase 2 exit) + this pack on merge.  
**Phase 3 status:** **Outlook only** — not started. No `PHASE_3_LOOP_PROMPTS.md`.  
**Authority:** [`tools/open-fdd-modernization/PHASE_3_EDGE_STREAMING_OUTLOOK.md`](../../tools/open-fdd-modernization/PHASE_3_EDGE_STREAMING_OUTLOOK.md)

Phase 3 is architectural foresight for live edge/MQTTS → React. It is **not**
authorization to change BACnet writes, fieldbus socket ownership, or MQTT topics.

## Prerequisites (from Phase 3 outlook)

| prerequisite | status | evidence |
|---|---|---|
| Versioned observation / job / run / finding / chart-dataset contracts | **PARTIAL** | Jobs/findings/reports/FDD series contracts exist (`API_CONTRACT_MATRIX`, `CONTRACT_CONVENTIONS` `openfdd.api.contract.v1`). **Live observation** schema (event time, sequence, quality, clock) **not** defined — blocks honest P3-M0. |
| React treats server state as server state | **MET** | Pages load via `apiFetch` → `/api/*`; job/findings revisions; session-config for durable maps |
| Asynchronous operation/event model | **PARTIAL** | `ASYNC_OPS.md` documents patterns; FDD run still sync `POST /api/fdd/run`; SSE/WebSocket reserved, not product |
| Rust-only package ingest + DataFusion pipeline | **MET** | `package.rs` + `/api/csv/import/*`; FDD via DataFusion; no Python on `compose.react.yml` |
| Centralized auth + capability discovery | **MET** | `/api/auth/*`, AuthPage; `/api/capabilities` + `react_ui` |
| Provenance / units / quality / timestamp semantics | **PARTIAL** | Mapping/roles/units on package path; live quality/clock policies not specified |
| Stable site/equipment/point identities | **PARTIAL** | Equipment via FDD APIs; CAP-SITE delete/selection **NOT_STARTED**; live point_id contract absent |
| Operational metrics + immutable releases | **MET** | `/api/ui/migration-metrics`; GHCR `:nightly` + `sha-*` publish |

## Blockers before P3-M0

1. Define live observation contract (P3-M0 fields) without changing fieldbus wire ownership.
2. Decide SSE vs WebSocket browser delivery; keep React off BACnet/MQTT sockets.
3. Explicit human auth for any live BACnet write / topic redesign work.

## Deferred product gaps (not Phase 3, not skill violations)

From `PHASE_2_QUALIFICATION.md` accepted risks: CAP-SITE / CAP-WEATHER / CAP-ECM;
historian metering rate→kWh PROVISIONAL; 38 rules PROVISIONAL; Streamlit source
archived in-tree; Plotly npm not required for Phase 2 exit.

---

## Streamlit→React skill compliance

Canonical: `tools/open-fdd-modernization/skills/streamlit-to-react/SKILL.md`  
Wrapper: `openfdd_agent_spec/skills/openfdd-streamlit-to-react/SKILL.md`

| rule | result | notes |
|---|---|---|
| Browser → central `/api` only | **PASS** | `frontend/web/src/api/client.ts` relative/`VITE_API_BASE`; no FastAPI/8501 |
| No FDD/analytics math in TypeScript | **PASS** | Clients post/get envelopes; monthlySum client mirrors API for parity only |
| No Python product runtime | **PASS** | `compose.react.yml`; Streamlit `ARCHIVED.md` + `streamlit-legacy` profile |
| Ledgers updated with UI work | **PASS** | `docs/migration/react-rust/` current through Phase 2 exit |
| Comparison target | **PASS (post-P2)** | Streamlit is archive/oracle, not shipping default |
| Policy CI | **PASS** | `architecture_react_policy_check` + `phase2_computation_policy_check` |

No code skill violations found requiring a fix in this pack. Spec/docs drift
(Streamlit-still-default in `openfdd_agent_spec`) corrected in the same PR.

## Digests

**Tip verified:** `9ef0411` (2026-08-01)

| workflow | run | result |
|---|---|---|
| Publish Open-FDD stack to GHCR | [30708116225](https://github.com/bbartling/open-fdd/actions/runs/30708116225) | **success** — tags `sha-9ef0411` + retarget `:nightly` for `openfdd-central`, `openfdd-ui`, `openfdd-fieldbus`, `openfdd-mqtt` |
| Publish Open-FDD MCP to GHCR | [30708116291](https://github.com/bbartling/open-fdd/actions/runs/30708116291) | **success** — `openfdd-mcp:sha-9ef0411` + `:nightly` |

Immutable pin: `OPENFDD_IMAGE_TAG=sha-9ef0411`.

**Note:** Local registry digest inspect requires `read:packages` (403 from this agent host). Operators with packages scope should confirm nightly↔sha digest equality per `CONTAINER_AGENT.md`. `compose.react.yml` references `openfdd-web` (build from `frontend/web`); stack GHCR currently publishes `openfdd-ui` (archived Streamlit) alongside central/fieldbus/mqtt — React SPA image is compose-build / future package until a dedicated web publish lands.

`docker compose -f docker/compose.react.yml config` → OK.

## Next

Authorized Phase 3 program would start at **P3-M0 live observation contract**
only — separate from this readiness pack.
