---
title: Lite vs Full
nav_order: 3
has_children: true
---

# Lite vs Full

Open-FDD ships two NF apps from one shared source. Pick the edition from the host, not from the building. Both read the same Haystack
model in NF ([data model](modeling.html)); they differ in whether a rule engine runs on the box.

| | **Lite** | **Full** |
|---|---|---|
| NF app id | `open-fdd-lite` | `open-fdd` |
| Source | [`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite) | [`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app) |
| Host | 1 GB, Raspberry Pi class | 2 GB or more; 4 GB or more is comfortable |
| FDD engine | none | Node DuckDB (`@duckdb/node-api` 2.0.1-r.1) with Parquet on disk, or TimescaleDB |
| Includes | dashboard, charts, points, NF BACnet server view, CSV export, RDF export, weather hook, `rdf` hook | Lite plus the FDD tab and the Overview RCx dashboard, fault points, SQL rules, SPARQL and `sparql-data` hooks |
| Scheduled hooks | `weather` every 20 min, `rdf` on request | `fdd` hourly, `weather` every 20 min, `sparql`, `sparql-data`, `rdf` on request |
| History it sees | NF's own, about 7 days | NF's, or long-range history from Timescale |
| Weather BACnet mirror | on by default | off by default |

Both write only their own result points and weather variables. Neither writes to field devices or adds a second historian.

## Use Lite when

- the host has about 1 GB of RAM (NF alone uses most of it);
- you only need live values, a week of trends, the model as Turtle and the BACnet server view;
- FDD runs elsewhere and you want a light local dashboard.

## Use Full when

- the host has 2 GB or more and you want faults, RCx charts and fault points in NF;
- you need history longer than the local Parquet window: enable NF's TimescaleDB connector and set the app option `timescale`. Rules then run in that database.
  See [`nf-app/timescale`](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale).

`engine: "auto"` uses Timescale on the Timescale build or when that option is set, and otherwise server-side DuckDB 2.0.1 (`@duckdb/node-api` `2.0.1-r.1`). History for that engine is Parquet on disk. The browser calls the NF API for charts. There is no DuckDB-WASM and no Python DuckDB runtime in the plugin. If `@duckdb/node-api` cannot load, the run fails. A config that names `sqlite` or `pglite` fails. Python `duckdb>=2.0.1` is only a test and parity dependency. PyPI fault tooling uses pandas.

## Rules of thumb

- Build, test and install from a PC, never on the small box. See [Normal Framework](normal-framework.html).
- Do not run both editions on one NF. Both ship a weather hook that writes the same variables.
- A small host that gets heavier work later is a reason to replace the host, not to squeeze Full onto it.

## Charts and export

Both editions include [Charts and export](charts.html). Screens and chart types are in the [UI guide](ui-guide.html).
