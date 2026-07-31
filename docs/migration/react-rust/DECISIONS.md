# Decisions — React / Rust modernization

Newest first. Record product/architecture calls only.

| Date | Decision | Status |
|------|----------|--------|
| 2026-07-31 | Widget primitives use native HTML + CSS tokens; PlotlyHost is a placeholder div until M5 chart parity (no plotly npm in M3) | Accepted |
| 2026-07-31 | Shared `WidgetBaseProps` + `widgetTestId()` convention for all parity controls | Accepted |
| 2026-07-31 | React shell keeps Jobs/Upload sidebar routes (M4 path) while top tabs mirror Streamlit `REQUIRED_MAIN_SECTIONS` | Accepted |
| 2026-07-31 | Streamlit has no checked-in theme; React navy/teal tokens + 21rem sidebar are the M3 geometry SoT | Accepted |
| 2026-07-31 | Seed ledgers from code inventory; UNKNOWN dispositions until M1 | Accepted |
| 2026-07-31 | ADR-001: React+TS SPA; central Rust backend; DataFusion FDD; no FastAPI sidecar; Streamlit default until Phase 2 | Accepted |
| 2026-07-31 | Program kit lives in-repo at `tools/open-fdd-modernization/` | Accepted |
| 2026-07-31 | Durable ledgers under `docs/migration/react-rust/` | Accepted |
