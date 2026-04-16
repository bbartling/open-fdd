---
title: Standalone FDD with pandas
nav_order: 11
nav_exclude: true
---

# Standalone FDD with pandas

**Pandas** is the open-source Python library for tabular and time-series data: DataFrames, indexing, aggregation, and a huge ecosystem of tools. It grew out of work by Wes McKinney at AQR (2008) and became a NumFOCUS project; it is now the de facto standard for data manipulation and analysis in Python and is so widely used in modern data science that it is hard to imagine doing data work without it. In Open-FDD, pandas is the **heart of number crunching**—all rule evaluation runs over pandas DataFrames—and it is a natural fit for FDD: time-aligned sensor columns, rolling windows, bounds and expression checks, and fault flags map directly onto DataFrame operations.

**`open-fdd` on PyPI** ships **`open_fdd.engine.RuleRunner`**: load a CSV (or any DataFrame), pass a **`column_map`**, run YAML rules, get fault flag columns — no database required. See [Engine-only deployment and external IoT pipelines](howto/engine_only_iot).

Typical uses:

- **One-off and scripted FDD** — Exported CSVs, heat pump dumps, ad‑hoc rule tuning.
- **Vendor / cloud pipelines** — `pip install open-fdd` in a job that already produces DataFrames.

A **full AFDD stack** (API, storage, graph tooling) is documented separately in **[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**; it uses this package for rule evaluation.

---

## More reading

[Home](index), [Overview](overview), [Getting started](getting_started), and [Expression rule cookbook](expression_rule_cookbook).
