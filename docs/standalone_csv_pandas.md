---
title: Standalone CSV / pandas
nav_order: 6
---

# Standalone FDD with pandas

**Pandas** is the open-source Python library for tabular and time-series data: DataFrames, indexing, aggregation, and a huge ecosystem of tools. It grew out of work by Wes McKinney at AQR (2008) and became a NumFOCUS project; it is now the de facto standard for data manipulation and analysis in Python and is so widely used in modern data science that it is hard to imagine doing data work without it. In Open-FDD, pandas is the **heart of number crunching**—all rule evaluation runs over pandas DataFrames—and it is a natural fit for FDD: time-aligned sensor columns, rolling windows, bounds and expression checks, and fault flags map directly onto DataFrame operations.

**`open-fdd` 2.x on PyPI** already ships **`open_fdd.engine.RuleRunner`**: load a CSV (or any DataFrame), point at the same YAML rules as the platform, get fault flag columns — no database required for that path. See [Engine-only deployment and external IoT pipelines](howto/engine_only_iot).

Typical uses:

- **One-off and scripted FDD** — Exported CSVs, heat pump dumps, ad‑hoc rule tuning.
- **Vendor / cloud pipelines** — `pip install open-fdd` in a job that already produces DataFrames.

The **edge platform** (TimescaleDB, Grafana, BACnet, API) remains **repo + Docker**; PyPI is the **library** slice.

---

## Full Docker platform

For TimescaleDB, BACnet, API, and UI, use the **[AFDD stack documentation](https://bbartling.github.io/open-fdd-afdd-stack/)** and [Getting started](https://bbartling.github.io/open-fdd-afdd-stack/getting_started) there.
