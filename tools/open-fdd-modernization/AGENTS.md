# Open-FDD React product UI agent guide

## Mission

Maintain React (`frontend/web`) as the sole production UI with domain authority
on **central Rust + DataFusion SQL**. Python is oracle/characterization only.
**No FastAPI sidecar.**

Phase 1+2 exits are approved. Phase 3 (edge/live streaming) is outlook-only —
see `PHASE_3_READINESS.md`. Do not redesign BACnet/MQTT without explicit auth.

This file is the modernization-kit `AGENTS.md`. It does **not** replace
[`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) or the repo
root [`AGENTS.md`](../../AGENTS.md).

## Mandatory skill + OS bootstrap (every UI PR)

Before editing React/product UI code, **read and follow** in order:

1. Repo root [`AGENTS.md`](../../AGENTS.md)
2. [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) — product law,
   ownership, PR protocol, Milestone skills
3. This file
4. [`AGENT_SKILL_BRIDGE.md`](AGENT_SKILL_BRIDGE.md) — which skill for which work
5. **[`openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`](../../openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md)**
6. [`AGENT_EXECUTION_SYSTEM.md`](AGENT_EXECUTION_SYSTEM.md)
7. Current phase doc + [`docs/migration/react-rust/`](../../docs/migration/react-rust/)
   ledgers
8. Matching skill from `openfdd_agent_spec/skills/` when the PR touches SQL FDD,
   cookbooks, GHCR, ECM, or architecture ownership

Do not invent a React redesign. Match documented product behavior and API contracts.

## Open-FDD repository map

```text
frontend/web/                    React SPA (sole production UI)
services/central/                Rust browser API + jobs + FDD orchestration
sql_rules/ + crates/fdd_*        DataFusion FDD / analytics
docs/migration/react-rust/       Durable ledgers + Phase 3 readiness
tools/open-fdd-modernization/    This program kit
openfdd_agent_spec/              Engineering agent OS + Milestone skills
open_fdd/                        PyPI oracle / ECM (not production FDD runtime)
```

## Source-of-truth hierarchy

1. Running React at the target viewport and state (product path).
2. Central `/api` contracts and ledgers under `docs/migration/react-rust/`.
3. Browser measurements and same-viewport screenshots when doing visual work.
4. Visual inference last — document uncertainty.

Document intentional differences. Prefer React + contract evidence.

## Required architecture (Open-FDD)

```text
React SPA ── same-origin /api ── central Rust ── DataFusion SQL
                                      │
                                      ├── jobs / mappings / artifacts
                                      └── fieldbus/MQTTS (unchanged)

Python ── oracle / characterization only (Phase 1)
```

### React owns

- Layout, components, tabs, responsive behavior, visible UI state.
- Form drafts, selections, open/closed panels, transient feedback.
- Loading, empty, disconnected, validation, and error presentation.
- Client downloads when no server authority is needed.

### central Rust owns

- APIs, authz, validation, durable jobs, persistence, orchestration.
- Ingestion, package/ZIP defenses, exports, error envelopes.
- Stable JSON contracts consumed by React.

### DataFusion / sql_rules owns

- Deterministic telemetry analytics and FDD rule execution.
- Never silently fall back to pandas in production paths.

### Python oracle owns

- Characterization fixtures, cookbook parity, optional ECM honesty checks.
- Never a browser-facing FastAPI or production UI dependency for React.

## React SPA skill law

Follow [`openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md`](../../openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md):

1. Inspect before editing (inventory widgets, session keys, branches).
2. Build a parity contract before pixel chasing.
3. Measure the product UI when browser tools exist.
4. Separate domain logic into Rust/SQL — not TypeScript formulas.
5. Translate shareable session keys into explicit React/URL/server state
   ([P1-M3-03](MILESTONE_PR_MATRIX.md)).
6. Verify with Vitest and Playwright where applicable.

For Open-FDD: **backend = `services/central` (Rust)**. Do not add a Python API sidecar.

## Migration workflow (bounded PRs)

1. Establish baseline (record viewport/fixture).
2. Inventory navigation, controls, session keys, downloads.
3. Capture visual/geometry specs (`LAYOUT_GEOMETRY.md` and ledgers).
4. Define/version Rust contracts before coupling React.
5. Implement React presentation only; reuse widgets from `frontend/web`.
6. Compare (exact / numeric / temporal / interaction / visual / artifact /
   security classes). UNKNOWN blocks DONE.
7. Update ledgers + `openfdd_agent_spec/SESSION_LOG.md` /
   `BUILD_CHECKPOINTS.md` when Phase 1 status changes.
8. One milestone ID per PR; CodeRabbit; green CI; squash-merge; prune.

## State translation

| UI state | Destination |
|---|---|
| Current tab / section | URL + React router (`main_section`) |
| Select / open panel | React local or URL state |
| Shareable job/equipment/site | URL search params |
| Calculation input | React form → Rust API |
| Calculation result | Query/cache from `/api/*` |
| Durable config / mapping | Rust jobs + FDD session-config |
| Auth | Server-side JWT / session validation |

Do not store authoritative job/mapping state only in `localStorage`.

## Calculation rules

- No pandas logic in TypeScript.
- No FastAPI bridge.
- No silent SQL → pandas fallback.
- Preserve BACnet write safety; React never touches BACnet wire.
- Distinguish raw values from presentation rounding.

## Minimum test coverage

- Contract/health and typed client compile.
- Widget/component interaction tests for new primitives.
- Route refresh/back/deep-link for session translation.
- Slice e2e for Jobs → upload → map → run (M4+) without Python UI container.
- Parity evidence rows updated in the same PR.

## Definition of done (shell / slice)

- Inventoried workflow migrated or explicitly waived in ledgers.
- React talks only to central `/api`.
- Production React build + affected CI green.
- Product UI compared at identical viewport/state when visual class applies.
- Intentional differences documented in `DECISIONS.md`.

## Related program docs

See [`README.md`](README.md) and [`AGENT_SKILL_BRIDGE.md`](AGENT_SKILL_BRIDGE.md).
