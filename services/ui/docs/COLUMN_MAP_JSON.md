# Column → Haystack point JSON mapping

Portable mapping so Streamlit can auto-run the cookbook without hand-editing every slider.

**CSVs are never rewritten.** Authors use **Project Haystack–style** JSON
(`siteRef`, `equip`, `device`, `equipType`, `points` like `discharge-air-temp`).
Rules consume those same point names on each equipment DataFrame.

## Pipeline

1. Load any building folder (Browse… or path) — leave historian files as-is
2. Copy the filled LLM prompt from **Data & Mapping** (or Auto-build heuristics)
3. Paste/load returned Haystack JSON
4. Apply map → Haystack-named columns on each equip DataFrame
5. Run rules; missing points → `SKIPPED_MISSING_ROLES`

## Files

| Path | Role |
| --- | --- |
| `app/column_map_json.py` | Normalize, LLM prompt, save/load |
| `docs/HAYSTACK_LIKE_MAPPING_GUIDE.md` | Point name table |
| Package `column_map.json` / per-equip sidecars | Site maps |

## UI

Streamlit **Data & Mapping**:

- Load / upload Haystack JSON
- Auto-build from loaded CSVs (exports `equip` / `points`)
- Filled LLM prompt with Streamlit code-block copy + `.txt` download

**Data Model** shows Haystack point → CSV column (points only). Topology
(AHU feeds / VAV fedBy) is a separate section.
