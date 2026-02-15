---
title: Standalone CSV & pandas (future)
nav_order: 11
---

# Standalone CSV & pandas (future)

A **future version** of Open-FDD on PyPI will offer a **standalone FDD mode** built around CSV files and pandas DataFrames. No database or edge platform required: load timeseries from CSV (or any DataFrame), run the same YAML rules and engine, and produce fault outputs as CSV-style reports or DataFrames. This will support:

- **One-off and scripted FDD** — Run FDD on exported CSVs (e.g. heat pump exports, building data dumps) for ad‑hoc analysis, tuning rules, or validating Brick models with SPARQL.
- **Vendor cloud use** — A cloud or MSI vendor could run the open-fdd rule engine (e.g. `pip install open-fdd`) in their own pipeline and apply FDD on pandas DataFrames they already have—enabling FDD in the cloud on data they pulled from Open-FDD or other sources.

The current repo focuses on the **edge platform** (TimescaleDB, Grafana, BACnet, API). The standalone CSV/pandas workflow is preserved in the repo for reference and will be packaged as a separate, installable mode in a future PyPI release.

---

## Archived workflows in the repo

The **[analyst/README.md](https://github.com/bbartling/open-fdd/blob/main/analyst/README.md)** directory in the repo contains archived documentation for the earlier static-CSV, AHU7 tutorial, and Brick-from-catalog workflows. Those flows use `analyst/run_all.sh`, `analyst/sparql/`, `analyst/rules/`, and `open_fdd/analyst/` (ingest, to_dataframe, brick_model, run_fdd). They remain available for note and as a basis for the future standalone CSV/pandas package.

For the current edge platform, use the main docs: [Home](index), [Overview](overview), [Getting Started](getting_started).
