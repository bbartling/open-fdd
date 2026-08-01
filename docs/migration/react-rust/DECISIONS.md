# Decisions — React / Rust modernization

Newest first. Record product/architecture calls only.

| Date | Decision | Status |
|------|----------|--------|
| 2026-07-31 | P1-M6-02 no-Python topology is `docker/compose.react.yml` (web+central+mqtt); Streamlit remains in compose.central for rollback | Accepted |
| 2026-07-31 | P1-M6-01 closes Python exit matrix with DELETE-P2 / ORACLE-ONLY / KEEP-AS-LIB / REPLACE only; Phase 2 deletions enumerated but not executed | Accepted |
| 2026-07-31 | M5-B plot datasets use SVG PlotlyHost stand-in (no plotly npm); figure JSON shape reserved for Plotly.react | Accepted |
| 2026-07-31 | FDD run is synchronous at `/api/fdd/run` (no run_id poll); React cancel = fetch AbortSignal; async job substrate reserved for longer ops | Accepted |
| 2026-07-31 | Mapping uses `?site=` as building_id for package inventory; durable maps via package/roles + session-config (not sessionStorage) | Accepted |
| 2026-07-31 | Shareable Streamlit session keys map to URL query (`job`/`eq`/`site`/`wl`/`section`); form drafts may use sessionStorage only | Accepted |
| 2026-07-31 | Phase 1 agents must follow `openfdd_agent_spec` + `streamlit-to-react` skill (via AGENT_SKILL_BRIDGE); FastAPI text in generic skill maps to central Rust | Accepted |
| 2026-07-31 | Widget primitives use native HTML + CSS tokens; PlotlyHost is a placeholder div until M5 chart parity (no plotly npm in M3) | Accepted |
| 2026-07-31 | Shared `WidgetBaseProps` + `widgetTestId()` convention for all parity controls | Accepted |
| 2026-07-31 | Package import has no job_id parameter; React shows `?job=` as display-only context until jobs↔dataset link lands | Accepted |
| 2026-07-31 | React shell keeps Jobs/Upload sidebar routes (M4 path) while top tabs mirror Streamlit `REQUIRED_MAIN_SECTIONS` | Accepted |
| 2026-07-31 | Streamlit has no checked-in theme; React navy/teal tokens + 21rem sidebar are the M3 geometry SoT | Accepted |
| 2026-07-31 | Seed ledgers from code inventory; UNKNOWN dispositions until M1 | Accepted |
| 2026-07-31 | ADR-001: React+TS SPA; central Rust backend; DataFusion FDD; no FastAPI sidecar; Streamlit default until Phase 2 | Accepted |
| 2026-07-31 | Program kit lives in-repo at `tools/open-fdd-modernization/` | Accepted |
| 2026-07-31 | Durable ledgers under `docs/migration/react-rust/` | Accepted |
