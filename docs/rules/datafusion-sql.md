---
title: SQL FDD lifecycle
parent: Rule Cookbook
nav_order: 6
nav_exclude: true
---

# SQL FDD lifecycle

Historical “DataFusion SQL” workbench notes. Tip engine: **Timescale** ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md)). Soft-OPEN ≠ FQ.

1. Author / tune in Lab or SQL FDD (`/sql-fdd`)
2. Validate against historian sample
3. Activate rule
4. `POST /api/fdd/run` → fault records

Catalog: [Timescale SQL cookbook](cookbook/datafusion-sql-cookbook.html).
