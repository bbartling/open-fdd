---
title: thrift advisory
parent: Operations
nav_order: 10
permalink: /operations/thrift-advisory.html
---

# Transitive dependency advisory tracking (Open-FDD 3.2.x)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

## thrift (CVE-2026-43868) — medium

**Chain (pre-3.3.15):** `open_fdd_edge_prototype` → `datafusion 43` → `parquet 53` → `thrift 0.17.0`

**Fixed in 3.3.15:** workspace upgraded to `datafusion 55` / `arrow 59` / `parquet 59` (thrift dropped from dependency tree).

**Why not bumped in 3.2.5:** `parquet` pins `thrift ^0.17`. `thrift 0.23.0` exists on crates.io but is incompatible with parquet 53 without upgrading the Arrow/DataFusion stack.

**Proper fix (tracked):** Upgrade to `datafusion 54+` / `arrow 59+` / `parquet 57+` where arrow-rs removed the thrift dependency ([arrow-rs#9962](https://github.com/apache/arrow-rs/pull/9962)).

**Risk posture (beta):** Parquet footer parsing only; edge does not expose a Thrift RPC server. Monitor via Dependabot + `cargo audit` in CI.

**2026-07-16 reaffirmation (PR-5 / #483):** Still not feasible to bump thrift without a DataFusion/Arrow stack upgrade. Documented dismiss / track-until-DF54+ remains the correct response for Dependabot thrift alerts. jsonwebtoken 9→10 is the actionable AppSec bump in this cycle.

**Do not** `[patch]` thrift to 0.23 without a full Arrow upgrade — build will break.
