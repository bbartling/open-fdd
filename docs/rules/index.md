---
title: Rule Cookbook
layout: default
nav_order: 7
has_children: true
permalink: /rules/
---

# Rule Cookbook

Open-source, **standards-first** HVAC fault detection. Production rules are **DataFusion SQL** against the Arrow/Parquet historian. Recipes use generic Haystack / SQL roles (`discharge-air-temp`, `outside-air-temp`, `fan-cmd`, …) — portable across modeled sites.

**Two catalogs (do not conflate):**

| Catalog | Role |
|---------|------|
| **DataFusion SQL** — [`sql_rules/registry.yaml`](https://github.com/bbartling/open-fdd/blob/master/sql_rules/registry.yaml) | **Production** FDD in Open-FDD central (`POST /api/fdd/run`) |
| **Pandas** — `open_fdd.rules` (`pip install "open-fdd[oracle]"`) | **Oracle / docs / notebooks** on PyPI |

## Start here

Screen sensors first, then the two rule catalogs. Everything else in this section is under Cookbook reference.

| Guide | Content |
|-------|---------|
| [**SQL anomaly detection**](sql-anomaly-detection.html) | First pass: Overview rolling Z-score screen + Lab tuners for `SV-*` / `PID-HUNT-1` / `WX-1` |
| [DataFusion SQL cookbook](cookbook/datafusion-sql-cookbook.html) | Full production SQL catalog |
| [Pandas cookbook](cookbook/pandas-cookbook.html) | Full pandas catalog, including FCU / `zone_other` |
| [Cookbook reference](cookbook/) | Taxonomy, schema, matrices, roadmap, macros, benchmarks, doc template, P0 catalog, and [FCU / zone_other](cookbook/fcu-zone-other.html) |

## Anomaly & sensor quality (quick map)

| Surface | Rules / API | Tuners |
|---------|-------------|--------|
| Overview **Anomaly screening (SQL)** | `POST /api/analytics/sql-anomaly` | `window_rows`, `z_threshold`, `method` (`zscore`\|`robust`), `transition_events` |
| Lab / FDD run | `SV-RANGE`, `SV-FLATLINE`, `SV-SPIKE`, `SV-STALE`, `SV-RATE`, `PID-HUNT-1`, `WX-1` | Lab sliders from `sql_rules/registry.yaml` |

Details, defaults, and hub flag (`OPENFDD_SQL_ANOMALY_SCREENING`): **[SQL anomaly detection](sql-anomaly-detection.html)**.

## Reference

| Guide | Content |
|-------|---------|
| [DataFusion SQL lifecycle](datafusion-sql.html) | Rule API, workbench, confirm |
| [Examples](examples.html) | Short illustrative queries |
| [SQL rules → Haystack map]({{ site.baseurl }}/modeling/sql-rules-haystack-map.html) | Every registry rule → Haystack tags / SQL roles |

UI: **SQL FDD Rules** (`/sql-fdd`) · **Lab** for tuners · **FDD Plots** for series overlays · Overview for the Z-score anomaly table.
