---
title: Compute boundary ownership inventory
parent: Architecture
nav_order: 13
---

# Compute boundary ownership inventory

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Audit:** 2026-09-08 · tip `e3c7660b` · Wave J Stage A  
**Machine-readable:** [compute_boundary_ownership.yaml](compute_boundary_ownership.yaml)

## Supersedes

[`PANDAS_USAGE_INVENTORY.md`](PANDAS_USAGE_INVENTORY.md) (2026-07-28) listed dozens of
`frontend/web/app/*.py` paths as React runtime. **Those paths do not exist on tip**
and must **not** be recreated. That file is retained only as a historical tombstone.

## Policy summary

| Category | Policy |
|----------|--------|
| Product Rust / SQL / Parquet | Required runtime |
| Product React SPA | Required presentation |
| PyPI pandas oracle / cookbook | External only |
| Offline WattLab / ECM tools | External only |
| Test / soak harnesses (may use Python drivers) | Allowed non-product |
| Deleted `frontend/web/app/` | Do not recreate |

Product must run with **no** Python interpreter in central/web/mqtt/fieldbus images
and no `OPENFDD_ALLOW_PANDAS_FDD` (Wave J J5 image gates).
