---
title: thrift advisory
parent: Operations
nav_order: 10
permalink: /operations/thrift-advisory.html
---

# Transitive dependency advisory tracking (Open-FDD 3.2.x)

## thrift (CVE-2026-43868 / GHSA-2f9f-gq7v-9h6m) — medium

| Field | Value |
| --- | --- |
| Advisory | CVE-2026-43868 · GHSA-2f9f-gq7v-9h6m |
| Dependabot | #29 (`Cargo.lock`), #32 (`edge/Cargo.lock` stale duplicate) |
| Locked package | `thrift 0.17.0` |
| Vulnerable range | `thrift <= 0.22.0` |
| Upstream fix | `thrift 0.23.0+` (crates.io) |
| Dependabot `first_patched_version` | `null` (Rust advisory mapping incomplete) |

### Dependency chain

```text
open_fdd_edge_prototype / fdd_*
  └── datafusion 43.0.0
        └── parquet 53.4.1
              └── thrift 0.17.0   (hard dep; not optional)
```

### Reachability

- Used only for **Parquet footer / Thrift metadata decoding** inside Arrow Parquet.
- Open-FDD does **not** expose a Thrift RPC server and does not accept untrusted Thrift RPC.
- Primary residual risk: **moderate DoS** while parsing crafted Parquet (CWE-789). Mitigate by ingesting **trusted** building datasets only.

### Why not patched in Phase 1

1. `parquet 53.x` pins `thrift ^0.17` → Cargo will **not** accept 0.23 via `[patch]`.
2. `parquet 54–58.x` still depends on thrift.
3. thrift was **removed** in `parquet 59+` ([arrow-rs#9962](https://github.com/apache/arrow-rs/pull/9962)).
4. Latest DataFusion **54** still depends on `parquet ^58.3` → **still pulls thrift**.
5. A safe clear requires Arrow/parquet **59+** and a DataFusion release that follows — out of Phase 1 scope.

### Time-bounded risk acceptance (Phase 1)

| Field | Value |
| --- | --- |
| Decision | **Accept** transitive thrift 0.17.0 risk for Open-FDD 3.2.x / Phase 1 |
| Owner | Open-FDD maintainers (`bbartling`) |
| Issue | [#483](https://github.com/bbartling/open-fdd/issues/483) |
| Accepted | 2026-07-13 |
| Review / expiry | **2026-10-13** (or next Arrow/DataFusion major bump, whichever first) |
| Follow-up | Track parquet 59+ / DataFusion upgrade; dismiss Dependabot #29/#32 with this rationale; delete stale `edge/Cargo.lock` when convenient |
| Mitigations | Trusted ingest only; AppSec CI (audit/Trivy); no public Parquet upload from unauthenticated users in production configs |

**Do not** `[patch]` thrift to 0.23 without a full Arrow upgrade — the build will break.

**Do not** close #483 as “fixed” until parquet-59-class evidence exists **or** this waiver is recorded and Dependabot alerts are formally dismissed with the expiry above.
