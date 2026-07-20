# Streamlit demo — agent specification

## Mission

Maintain **Vibe Code App 19** as a lightweight **educational pandas/Streamlit FDD demo** for BUILDING_100-style CSV data.

## Do not

- Re-add Rust or DataFusion to this repo
- Re-add Haystack/Oxigraph model services
- Turn this into Open-FDD or claim production parity
- Commit client historian CSV trees or generated caches
- Add FastAPI product architecture unless explicitly requested

## Open-FDD

The production Rust/DataFusion engine lives at:

`C:\Users\ben\Documents\open-fdd`

Port inventory: `docs/PORT_FROM_VIBE19_INVENTORY.md` (in Open-FDD repo).

## Do

- Keep rules **readable** in `app/rules/`
- Keep BUILDING_100 demo path easy (`HVAC_DATA_ROOT`, `configs/building_100.yaml`)
- Support CSV upload, local folder, read-only SQLite/DuckDB
- Use `st.cache_data` for expensive loads
- Test with small fixtures under `tests/`
- Update `docs/STREAMLIT_DEMO_SPEC.md` when behavior changes

## Entry point

```bash
cd vibe_code_apps_19
streamlit run streamlit_app.py
```

## Tests

```bash
python -m pytest -q
```
