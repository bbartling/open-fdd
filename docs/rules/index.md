---
title: Rule Cookbook
layout: default
nav_order: 7
has_children: true
permalink: /rules/
---

# Rule Cookbook

Production FDD is **Timescale / PostgreSQL SQL** (`sql/fdd`, [ADR-010](../architecture/adr-010-timescale-hard-cutover.md)). Soft-OPEN ≠ FQ. Pandas is oracle-only.

| Catalog | Count | Role |
|---------|------:|------|
| Timescale SQL (`sql/fdd` + registry) | **77** | Production (`POST /api/fdd/run`) |
| Pandas (`open_fdd.rules`) | **71** | Oracle / notebooks |

## Human guides

| Guide | Content |
|-------|---------|
| [SQL anomaly detection](sql-anomaly-detection.html) | Overview Z-score + Lab `SV-*` |
| [Timescale SQL cookbook](cookbook/datafusion-sql-cookbook.html) | Production SQL catalog |
| [Pandas cookbook](cookbook/pandas-cookbook.html) | Oracle catalog |
| [SQL analytics](sql-analytics-cookbook.html) | Overview / RCx SQL pack |
| [Pandas analytics](pandas-analytics-cookbook.html) | Oracle analytics |
| [DB design]({{ site.baseurl }}/modeling/#database-design-timescale) | Timescale tables |

## Anomaly quick map

| Surface | API / rules |
|---------|-------------|
| Overview screening | `POST /api/analytics/sql-anomaly` |
| Lab FDD | `SV-*`, `PID-HUNT-1`, `WX-1` via registry |

UI: **Lab** · **SQL FDD** · **FDD Plots** · Overview anomaly table.
