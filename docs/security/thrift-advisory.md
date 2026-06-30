---
title: thrift advisory
parent: Operations
nav_order: 10
permalink: /operations/thrift-advisory.html
---

# Transitive dependency advisory tracking (Open-FDD 3.2.x)

## thrift (CVE-2026-43868) — medium

**Chain:** `open_fdd_edge_prototype` → `datafusion 43` → `parquet 53` → `thrift 0.17.0`

**Why not bumped in 3.2.5:** `parquet` pins `thrift ^0.17`. `thrift 0.23.0` exists on crates.io but is incompatible with parquet 53 without upgrading the Arrow/DataFusion stack.

**Proper fix (tracked):** Upgrade to `datafusion 54+` / `arrow 59+` / `parquet 57+` where arrow-rs removed the thrift dependency ([arrow-rs#9962](https://github.com/apache/arrow-rs/pull/9962)).

**Risk posture (beta):** Parquet footer parsing only; edge does not expose a Thrift RPC server. Monitor via Dependabot + `cargo audit` in CI.

**Do not** `[patch]` thrift to 0.23 without a full Arrow upgrade — build will break.
