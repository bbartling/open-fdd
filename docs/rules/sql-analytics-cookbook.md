---
title: SQL analytics cookbook
parent: Rule Cookbook
nav_order: 4
permalink: /rules/sql-analytics-cookbook/
---

# SQL analytics cookbook

Overview / RCx / plant-health equations are versioned **PostgreSQL SQL** under `sql/analytics/` (pack hash with `sql/contract`). Soft-OPEN ≠ FQ.

| Piece | Location |
|-------|----------|
| Query bodies | `sql/analytics/postgres/queries/*.sql` |
| Inventory | `sql/analytics/registry.json` |
| Historian | Timescale `sample` + dims ([Modeling]({{ site.baseurl }}/modeling/)) |

Rust binds `$1` site/building only — no equation forks in product code. UI calls `/api/analytics/*`.

See [ADR-010](../architecture/adr-010-timescale-hard-cutover.md) · [TIMESCALE_WAVE_X](../operations/TIMESCALE_WAVE_X.md).
