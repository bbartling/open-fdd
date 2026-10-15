# Open-FDD stress gate (SPARQL → Timescale → SQL FDD ≈ pandas)

Soft-OPEN Track C port of the BPS `scripts/stress/` agent harness. Same scientific
lesson (SPARQL → timeseries → pandas ↔ warehouse SQL); Open-FDD route names and
JWT auth. **Soft-OPEN ≠ FQ.** Synthetic sites only — no private consumer names.

Vocabulary is **Project Haystack RDF** / package `ofdd:` Turtle. Production FDD
is **Timescale SQL** on tip Soft-OPEN; pandas runs **only** in this gate (and
oracle CI) — never on the product request path.

## What we prove (gate matrix)

| Gate | Script | Proof | Soft-OPEN status |
| --- | --- | --- | --- |
| A1 | `01_sparql_model.py` | SPARQL + package TTL + predefined catalog | Landed (T13) |
| A2 | `02_sparql_fc1_points.py` | FC1 roles via SPARQL / templates | Optional later |
| A3 | `03_sparql_zone_dataframe.py` | SPARQL → point-resolve/historian → pandas DF | Landed (T13) |
| B–E | `04`–`07` | Local Timescale / warehouse (may stay BPS-side) | Optional |
| F | `08_sql_vs_pandas_sparql.py` | Synthetic pack SQL FDD ↔ pandas via SPARQL DF; fail-closed (#1253) | Landed (T14) |
| G | `09_analytics_sql_vs_pandas.py` | Analytics SQL ↔ independent pandas | Landed (T15) |
| H | `10_model_crud_helpers.py` | `PUT /api/model/semantic-meta` dry_run + CAS; `GET /api/model/ttl` | Soft-OPEN (≠ full BPS overlay) |
| Runner | `run_gate.py` + `helpers.py` | `--host` / `--base-url` JWT | **This PR (T12)** |

## Open-FDD API map (vs BPS)

| Need | Open-FDD | BPS twin |
| --- | --- | --- |
| Login | `POST /api/auth/login` → `token` / `access_token` | same path, `access_token` |
| Health | `GET /api/health` (`ok`) | same |
| SPARQL | `POST /api/model/sparql` + `building_id` | `POST /api/sparql` |
| Catalog | `GET /api/model/sparql/predefined` | examples catalog |
| TTL | `GET /api/csv/import/package/mapping/ttl?building_id=` | `GET /api/model/ttl` |
| Readings | `GET /api/timeseries/readings` | `GET /api/points/{id}/timeseries` |
| Historian | `GET\|POST /api/historian/query` | point timeseries |
| Default port | **8080** | often 8090 |

## Run — Linux on the lab box

```bash
./scripts/openfdd_stack_up.sh react-ot   # or csv / Timescale Soft-OPEN stack
export OPENFDD_AGENT_PASSWORD=…          # never commit
export OPENFDD_STRESS_BUILDING_ID=SYNTH_01   # synthetic id only
python scripts/stress/run_gate.py --building-id SYNTH_01
```

## Run — Windows laptop → lab API

```bat
set OPENFDD_AGENT_PASSWORD=…
python scripts\stress\run_gate.py --host <lab-ip> --building-id SYNTH_01
```

Non-localhost `--host` (or `--remote-api`) skips local-DB-only steps. Full URL:

```bat
python scripts\stress\run_gate.py --base-url http://<lab-ip>:8080 --building-id SYNTH_01
```

Env: `OPENFDD_STRESS_BASE` / `OPENFDD_API_BASE`, `OPENFDD_STRESS_USER`,
`OPENFDD_STRESS_PASS` / `OPENFDD_AGENT_PASSWORD`, `OPENFDD_STRESS_BUILDING_ID`.

Deps: stdlib only for helpers/runner. Gate scripts that build DataFrames need
`pip install pandas` (and `open-fdd[oracle]` for pandas rule oracles).

## Beginner path

Prefer [`scripts/lessons/`](../lessons/) for a human/agent teach walkthrough, then
this gate for regression.

## Related

- BPS parity audit (ART): Soft-OPEN Track C / issue [#1253](https://github.com/bbartling/open-fdd/issues/1253)
- Haystack RDF: [#997](https://github.com/bbartling/open-fdd/issues/997), [#1123](https://github.com/bbartling/open-fdd/issues/1123)
