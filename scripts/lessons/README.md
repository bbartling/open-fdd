# Beginner lessons — SPARQL → pandas → SQL (Open-FDD Soft-OPEN)

Teaching twin of [`scripts/stress/`](../stress/). Same JWT `--host` / `--base-url`
helpers. Soft-OPEN ≠ FQ. **Synthetic `building_id` only** — never hardcode private
consumer campus names in scripts or docs.

Vocabulary: **Project Haystack RDF** / package `ofdd:` Turtle via central
`POST /api/model/sparql` and package TTL routes.

## Point at the API

| Where you run | Command |
| --- | --- |
| Lab box (localhost) | `python scripts/lessons/… --building-id SYNTH_01` |
| Windows / LAN laptop | `python scripts/lessons/… --host 192.168.204.55 --building-id SYNTH_01` |
| Full URL | `--base-url http://192.168.204.55:8080` |

Defaults: `http://127.0.0.1:8080`. Env: `OPENFDD_API_BASE`, `OPENFDD_AGENT_PASSWORD`,
`OPENFDD_STRESS_BUILDING_ID`.

## Lessons (land with Track C follow-ups)

| Lesson | Script | Topic |
| --- | --- | --- |
| 01 | `lesson_01_sites_and_equipment.py` | Health + SPARQL list equipment (T13+) |
| 02 | `lesson_02_fc1_points.py` | SPARQL → FC1 / role point ids |
| 03 | `lesson_03_fc1_dataframe.py` | Historian/timeseries → pandas DF |
| 04 | `lesson_04_pandas_vs_sql.py` | Local pandas ≈ server SQL FDD hours |

Companion `.rq` files for Swagger / `POST /api/model/sparql` live in [`sparql/`](sparql/).

## Windows notes

- Consoles default to cp1252; helpers force UTF-8 / replace so arrows never crash.
- Install: `pip install pandas` when DataFrame lessons land; helpers use stdlib only.
