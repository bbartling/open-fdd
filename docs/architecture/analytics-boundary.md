---
title: Analytics boundary
parent: Architecture
nav_order: 12
---

# Analytics boundary

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status:** **active product contract** (Wave J Stage A, 2026-09-08).

## Boundary

```text
React SPA → typed /api/analytics/* → central Rust → DataFusion SQL and/or
central-analytics-v1 inline Rust → Arrow/JSON → UI render only
```

Do not scatter ad-hoc SQL through React. Do not reintroduce `frontend/web/app/*.py`
(removed; historical inventory only).

## Domains

runtime · sensor_health · weather · economizer · comfort · airside · hydronic ·
mechanical_cooling · metering · schedules · equipment · rcx · wattlab_exports

Each domain: typed inputs, params, SQL or documented Rust path, null/unit rules, tests.

## Engine labels (honest)

| Label | Meaning |
|-------|---------|
| `datafusion` | Historian / package Parquet via DataFusion SQL |
| `central-analytics-v1` | Deterministic Rust compute on registered samples (not “secret pandas”) |

An engine label alone is not qualification — dispatch path + plan/fixture evidence required (Wave J J5/J6).

## Today

- FDD: `sql_rules/` + `crates/fdd_rules` (production)
- Analytics: `services/central/src/analytics/` + `POST /api/analytics/*`
- SPA: `frontend/web/src/` (Overview tables, RCx/Inspect Plotly) — **no** local pandas FDD

No arbitrary operator SQL editor. Integrator SQL lab (if any) is separate and gated.

SoT: [`openfdd_agent_spec/ARCHITECTURE.md`](../../openfdd_agent_spec/ARCHITECTURE.md) · [compute_boundary_ownership.yaml](compute_boundary_ownership.yaml).
