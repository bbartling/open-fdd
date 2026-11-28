---
title: Lite vs Full
nav_order: 3
has_children: true
---

# Lite vs Full

Open-FDD ships two NF apps from one shared source. Pick the edition from the host, not from the building. Both read the same Haystack
model in NF ([data model](modeling.html)).

| | **Lite** | **Full** |
|---|---|---|
| NF app id | `open-fdd-lite` | `open-fdd` |
| Source | [`lite/`](https://github.com/bbartling/open-fdd/tree/master/lite) | [`nf-app/`](https://github.com/bbartling/open-fdd/tree/master/nf-app) |
| Host | 1 GB, Raspberry Pi class | 2 GB or more; 4 GB or more is comfortable |
| FDD engine | DuckDB, hourly | DuckDB build (Node `@duckdb/node-api` 2.0.1-r.1, Parquet on disk) or Timescale build |
| Includes | dashboard, charts, points, NF BACnet server view, CSV export, RDF export, weather hook, `rdf` and `sparql` hooks | Lite plus the FDD tab and the Overview RCx dashboard, fault points, SQL rules and the `sparql-data` hook |
| Scheduled hooks | `fdd` hourly, `weather` every 20 min; `rdf` and `sparql` on request | `fdd` hourly, `weather` every 20 min; `sparql`, `sparql-data` and `rdf` on request |
| History it sees | NF's own, about 7 days | NF's, or long-range history from Timescale |
| Weather BACnet mirror | on by default | off by default |

## Use Lite when

- the host has about 1 GB of RAM (NF alone uses most of it);
- you only need live values, a week of trends, the model as Turtle and the BACnet server view;
- you want the hourly DuckDB rule run, without the Full screens.

## Use Full when

- the host has 2 GB or more and you want faults, RCx charts and fault points in NF. A single site uses the DuckDB build (Parquet on disk). Several sites, or history you want in Timescale, use the Timescale build: enable NF's TimescaleDB connector and set the app option `timescale`.
  See [`nf-app/timescale`](https://github.com/bbartling/open-fdd/tree/master/nf-app/timescale).

`auto` runs DuckDB unless this is the Timescale build or `timescale` is set. A missing package, or `sqlite` or `pglite`, fails the run.

## Charts and export

Both editions include [Charts and export](charts.html). Screens and chart types are in the [UI guide](ui-guide.html).
