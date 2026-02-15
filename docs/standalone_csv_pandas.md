---
title: Standalone FDD with pandas
nav_order: 11
---

# Standalone FDD with pandas

**Pandas** is the open-source Python library for tabular and time-series data: DataFrames, indexing, aggregation, and a huge ecosystem of tools. It grew out of work by Wes McKinney at AQR (2008) and became a NumFOCUS project; it is now the de facto standard for data manipulation and analysis in Python and is so widely used in modern data science that it is hard to imagine doing data work without it. In Open-FDD, pandas is the **heart of number crunching**—all rule evaluation runs over pandas DataFrames—and it is a natural fit for FDD: time-aligned sensor columns, rolling windows, bounds and expression checks, and fault flags map directly onto DataFrame operations.

A **future version** of Open-FDD on PyPI will offer a **standalone FDD mode** built around CSV files and pandas DataFrames. No database or edge platform required: load timeseries from CSV (or any DataFrame), run the same YAML rules and engine, and produce fault outputs as CSV-style reports or DataFrames. This will support:

- **One-off and scripted FDD** — Run FDD on exported CSVs (e.g. heat pump exports, building data dumps) for ad‑hoc analysis, tuning rules, or validating Brick models with SPARQL.
- **Vendor cloud use** — A cloud or MSI vendor could run the open-fdd rule engine (e.g. `pip install open-fdd`) in their own pipeline and apply FDD on pandas DataFrames they already have—enabling FDD in the cloud on data they pulled from Open-FDD or other sources.

The current repo focuses on the **edge platform** (TimescaleDB, Grafana, BACnet, API). The standalone CSV/pandas workflow is preserved in the repo for reference and will be packaged as a separate, installable mode in a future PyPI release.

---

## Archived workflows in the repo

The **[analyst/README.md](https://github.com/bbartling/open-fdd/blob/main/analyst/README.md)** directory in the repo contains archived documentation for the earlier static-CSV, AHU7 tutorial, and Brick-from-catalog workflows. Those flows use `analyst/run_all.sh`, `analyst/sparql/`, `analyst/rules/`, and `open_fdd/analyst/` (ingest, to_dataframe, brick_model, run_fdd). They remain available for note and as a basis for the future standalone CSV/pandas package.

For the current edge platform, use the main docs: [Home](index), [Overview](overview), [Getting Started](getting_started).
