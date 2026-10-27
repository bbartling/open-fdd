# Beginner lessons — SPARQL → pandas → open_fdd + RDF mutate

Teaching twin of [`scripts/stress/`](../stress/). Same JWT `--host` / `--base-url`
helpers. Soft-OPEN ≠ FQ. **Synthetic `building_id` only**.

## Point at the API

| Where | Command |
| --- | --- |
| Local stack | `python scripts/lessons/… --base-url http://127.0.0.1:8080 --building-id SYNTH_03` |
| Lab LAN | `python scripts/lessons/… --host <lab-ip> --building-id SYNTH_03` |

Env: `OPENFDD_API_BASE`, `OPENFDD_AGENT_PASSWORD` (or admin), `OPENFDD_STRESS_BUILDING_ID`.

## Lessons

| # | Script | Proves |
| --- | --- | --- |
| 01 | `lesson_01_sites_and_equipment.py` | Health + SPARQL list equipment |
| 03 | `lesson_03_fc1_dataframe.py` | SPARQL → point-resolve → **pandas DF** → **`open_fdd.rules` FC1** |
| 05 | `lesson_05_rdf_semantic_meta_put.py` | **GET/PUT `/api/model/semantic-meta`** (dry_run + CAS write + restore) |

Needs for 03: `pip install pandas open-fdd pyyaml`.

Fixture: [`scripts/fixtures/softopen/SYNTH_03_timeseries_semantic_meta.zip`](../fixtures/softopen/).
