# Open-FDD Streamlit → React agent guide

## Mission

Preserve Streamlit (`services/ui`) as the behavioral and visual reference while
building `frontend/web` so a user cannot tell them apart on graded workflows.
Domain authority stays on **central Rust + DataFusion SQL**. Python is
oracle/characterization only during Phase 1. **No FastAPI sidecar.**

This file is the modernization-kit `AGENTS.md`. It does **not** replace
[`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) or the repo
root [`AGENTS.md`](../../AGENTS.md).

## Mandatory skill + OS bootstrap (every Phase 1 PR)

Before editing React/Streamlit/parity code, **read and follow** in order:

1. Repo root [`AGENTS.md`](../../AGENTS.md)
2. [`openfdd_agent_spec/AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) — product law,
   ownership, PR protocol, Milestone skills
3. This file
4. [`AGENT_SKILL_BRIDGE.md`](AGENT_SKILL_BRIDGE.md) — which skill for which work
5. **[`skills/streamlit-to-react/SKILL.md`](skills/streamlit-to-react/SKILL.md)** and
   the relevant reference under `skills/streamlit-to-react/references/`
6. [`AGENT_EXECUTION_SYSTEM.md`](AGENT_EXECUTION_SYSTEM.md)
7. Current phase doc + [`docs/migration/react-rust/`](../../docs/migration/react-rust/)
   ledgers
8. Matching skill from `openfdd_agent_spec/skills/` when the PR touches SQL FDD,
   cookbooks, GHCR, ECM, or architecture ownership

Do not invent a React redesign. Port measurable Streamlit behavior.

## Open-FDD repository map

```text
services/ui/streamlit_app.py     Streamlit reference (default product UI)
services/ui/app/                 Streamlit modules
services/central/                Rust browser API + jobs + FDD orchestration
sql_rules/ + crates/fdd_*        DataFusion FDD / analytics
frontend/web/                    React SPA (Phase 1, flag-gated)
docs/migration/react-rust/       Durable ledgers
tools/open-fdd-modernization/    This program kit
openfdd_agent_spec/              Engineering agent OS + Milestone skills
open_fdd/                        PyPI oracle / ECM (not production FDD runtime)
```

## Source-of-truth hierarchy

1. Running Streamlit at the target viewport and state.
2. Streamlit source, assets, and `dashboard_contract.py` section order.
3. Browser measurements and same-viewport screenshots.
4. Installed Streamlit defaults when no theme is checked in.
5. Visual inference last — document uncertainty.

Prefer the running reference when evidence conflicts. Document intentional
differences (for example React Jobs routes ahead of Streamlit Jobs wiring).

## Required architecture (Open-FDD)

```text
Streamlit reference ── visual/behavioral specification

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
- Stable JSON contracts consumed by React (and Streamlit clients).

### DataFusion / sql_rules owns

- Deterministic telemetry analytics and FDD rule execution.
- Never silently fall back to pandas in production paths.

### Streamlit owns

- Reference workflow until React parity is accepted and Phase 2 cuts over.
- Runnable comparison target.
- No new duplicated business logic during Phase 1.

### Python oracle owns

- Characterization fixtures, cookbook parity, optional ECM honesty checks.
- Never a browser-facing FastAPI or production UI dependency for React.

## Streamlit-to-React skill law

Follow [`skills/streamlit-to-react/SKILL.md`](skills/streamlit-to-react/SKILL.md):

1. Inspect before editing (inventory widgets, session keys, branches).
2. Build a parity contract before pixel chasing.
3. Measure the reference when browser tools exist.
4. Separate domain logic into Rust/SQL — not TypeScript formulas.
5. Translate `st.session_state` into explicit React/URL/server state
   ([P1-M3-03](MILESTONE_PR_MATRIX.md)).
6. Verify with [`references/parity-verification.md`](skills/streamlit-to-react/references/parity-verification.md).
7. Map widgets via [`references/component-mapping.md`](skills/streamlit-to-react/references/component-mapping.md).

When [`references/sidecar-architecture.md`](skills/streamlit-to-react/references/sidecar-architecture.md)
mentions FastAPI, **substitute central Rust** for Open-FDD. Do not add a Python
API sidecar.

## Migration workflow (bounded PRs)

1. Establish baseline (Streamlit runs; record viewport/fixture).
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

| Streamlit state | Destination |
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
- Reference vs React compared at identical viewport/state when visual class applies.
- Intentional differences documented in `DECISIONS.md`.

## Related program docs

See [`README.md`](README.md) and [`AGENT_SKILL_BRIDGE.md`](AGENT_SKILL_BRIDGE.md).
