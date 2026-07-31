# Open-FDD UI (Streamlit vibe19)

**Current default product UI:** Streamlit (`streamlit_app.py` → `openfdd-ui`).

**Phase 1+ modernization:** React SPA is authorized behind a feature flag per
[ADR-001](../../docs/architecture/adr-001-react-rust-modernization.md) and
[`docs/migration/react-rust/`](../../docs/migration/react-rust/README.md).
Do **not** start React feature work before the M0 ledger gate. Do **not** add a
FastAPI/Python sidecar for the SPA — browser → central Rust `/api` only.

- Keep the Streamlit UX (sidebar **Rule tuning** sliders, 8 sections) intact
  while it remains the default / fallback.
- FDD execution is **DataFusion SQL via central** (`app/central_client.py` → `/api/fdd/run`).
- Do **not** reintroduce pandas rule math for Run Rules.
- Do **not** recreate Oxigraph/RDF UIs.
- **Delete site** removes Feather/parquet/results for the selected building_id; session sliders stay.
