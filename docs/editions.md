---
title: DuckDB vs Timescale
nav_order: 3
has_children: true
---

# DuckDB vs Timescale

Open-FDD is one product with two storage backends. Both read the same Haystack model in NF ([data model](modeling.html)). Pick the backend from the deployment.

| | **DuckDB** | **Timescale** |
|---|---|---|
| Recommended for | One building: an edge box, a Raspberry Pi, or another embedded host | Several sites, a campus, or a portfolio |
| History | Parquet on disk, Node `@duckdb/node-api` 2.0.1-r.1 | NF's TimescaleDB connector |
| Current install | [`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite), app id `open-fdd-lite` | [`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app), app id `open-fdd` |
| Screens | Overview, Charts, Backend server, Model/RDF | Those, plus Analytics, Fault detection, Export, and the Overview retro-commissioning panels |

`engine: auto` uses Timescale on a Timescale install or when the `timescale` option is set. Otherwise it uses DuckDB. `sqlite` and `pglite` are not backends. Naming either fails the run.

Charts and CSV export are in [Charts and export](charts.html). Screens are in the [UI guide](ui-guide.html).
