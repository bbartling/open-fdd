# Open-FDD UI (Streamlit vibe19)

- Keep the Streamlit UX (sidebar **Rule tuning** sliders, 8 sections) intact.
- FDD execution is **DataFusion SQL via central** (`app/central_client.py` → `/api/fdd/run`).
- Do **not** reintroduce pandas rule math for Run Rules.
- Do **not** recreate React or Oxigraph/RDF UIs.
- **Delete dataset** removes Feather/parquet by Haystack/building id; session sliders stay.
