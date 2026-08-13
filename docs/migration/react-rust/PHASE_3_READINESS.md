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
historian metering rate→kWh PROVISIONAL; 38 rules PROVISIONAL; React source
archived in-tree; Plotly npm not required for Phase 2 exit.

---

## React SPA skill compliance

Canonical: `tools/open-fdd-modernization/openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`  
Wrapper: `openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`

| rule | result | notes |
|---|---|---|
| Browser → central `/api` only | **PASS** | `frontend/web/src/api/client.ts` relative/`VITE_API_BASE`; no FastAPI/8501 |
| No FDD/analytics math in TypeScript | **PASS** | Clients post/get envelopes; monthlySum client mirrors API for parity only |
| No Python product runtime | **PASS** | `compose.react.yml`; React SPA only |
| Ledgers updated with UI work | **PASS** | `docs/migration/react-rust/` current through Phase 2 exit |
| Comparison target | **PASS (post-P2)** | React is archive/oracle, not shipping default |
| Policy CI | **PASS** | `architecture_react_policy_check` + `phase2_computation_policy_check` |

No code skill violations found requiring a fix in this pack. Spec/docs drift
(React SPA-still-default in `openfdd_agent_spec`) corrected in the same PR.

## Digests

**Tip verified:** `61fee63` (2026-08-01)

| workflow | run | result |
|---|---|---|
| Publish Open-FDD stack to GHCR | [30710271297](https://github.com/bbartling/open-fdd/actions/runs/30710271297) | **success** — tags `sha-61fee63` + retarget `:nightly` for `openfdd-central`, `openfdd-web`, `openfdd-fieldbus`, `openfdd-mqtt` |
| Publish Open-FDD MCP to GHCR | [30710271292](https://github.com/bbartling/open-fdd/actions/runs/30710271292) | **success** — `openfdd-mcp:sha-61fee63` + `:nightly` |

Immutable pin: `OPENFDD_IMAGE_TAG=sha-61fee63`.

Local pull smoke (nightly ↔ sha digest equality confirmed):

| image | digest |
|---|---|
| `ghcr.io/bbartling/openfdd-central` | `sha256:6bb9efe10240dab920781bec7dafbb76ec776d7b942aa34d878984f9e71fead0` |
| `ghcr.io/bbartling/openfdd-web` | `sha256:46d453e121abc3b33914520b0c7ae62a1064ff78d14c24f43d8235801d4f8e45` |
| `ghcr.io/bbartling/openfdd-fieldbus` | `sha256:5ea6a1bf6071d2f7bad71712b36cb295f37b0f2f9ea4fba2e6b8943a36282486` |
| `ghcr.io/bbartling/openfdd-mqtt` | `sha256:c7c094d79536969b75b9038487c88071498d3cac0a37910f3a1d8c3a55934121` |
| `ghcr.io/bbartling/openfdd-mcp` | `sha256:b8ef84859af54217051f2b966b3902e5bcb6fef84b5a62e13baf3342bf4a6072` |

**Note:** `compose.react.yml` references `openfdd-web` (build from `frontend/web`); stack GHCR publishes `openfdd-web` (archived React) alongside central/fieldbus/mqtt — React SPA image is compose-build / future package (`openfdd-web:nightly` not published).

`docker compose -f docker/compose.react.yml config` → OK.

## Next

Authorized Phase 3 program would start at **P3-M0 live observation contract**
only — separate from this readiness pack.
