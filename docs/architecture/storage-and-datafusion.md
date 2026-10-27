---
title: Timescale historian & SQL
parent: Architecture
nav_order: 3
---

# Timescale historian & SQL

> Replaces the old “Storage & DataFusion” page. Soft-OPEN ≠ FQ.

| Contract | Tip |
|----------|-----|
| Historian | **TimescaleDB** (`OPENFDD_DATABASE_URL`, `OPENFDD_HISTORIAN=timescale`) |
| FDD / analytics | Versioned `.sql` packs (`sql/fdd`, `sql/analytics`) |
| Forbidden | Dual-write, Parquet/DataFusion co-canonical ([ADR-010](adr-010-timescale-hard-cutover.md)) |

## Bring-up

See [TIMESCALE_WAVE_X](../operations/TIMESCALE_WAVE_X.md). Soft-OPEN local stack/ACME: no site backups unless asked; dual-write false.

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rules` | List rules |
| POST | `/api/fdd/run` | Run registry FDD |
| POST | `/api/analytics/*` | Overview / RCx SQL |

Catalog: [Rule Cookbook]({{ site.baseurl }}/rules/). Schema: [Modeling → DB design]({{ site.baseurl }}/modeling/#database-design-timescale).
