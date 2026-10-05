---
title: Haystack RDF perf budgets (C5 H14)
parent: Operations
nav_order: 96
---

# Haystack RDF — performance budgets (H14 / #1003)

Define budgets **before** measuring. Large-host measurement skipped on bensbench
is a **PARTIAL** claim — never greenwash as FQ.

| Workload | Budget (initial) | Measure |
| --- | --- | --- |
| Cold dataset materialize (≤50 equip, ≤500 points) | p95 ≤ 5 s; peak RSS delta ≤ 512 MiB | `haystack_central_dataset::materialize` |
| Warm cache hit (same revision+inventory token) | p95 ≤ 50 ms | central `HaystackRdfCache` |
| SPARQL template `fdd_role_candidates` | p95 ≤ 2 s; rows ≤ 2000 | `haystack_sparql_bindings` |
| Consumer bundle (FDD+history+ECM) | p95 ≤ 2.5 s | `/api/model/sparql/consumers` |
| Concurrent tenants (2) | no cross-tenant cache key collision | dual inventory tokens |
| Cancellation | cooperative between batches; no late publish | #1127 cancellation tip |

**Claim rules:** skipped large fixtures → `PARTIAL`. Missing artifact → FAIL.
Cookbooks untouched. MQTTS continuity unchanged by this path.

## Qualification honesty (Q05 / Q06)

Do not mark these **VERIFIED** until executable evidence exists on the cited profile.

| Work item | Status | Close only when |
| --- | --- | --- |
| **H12** — full package ZIP → Haystack RDF → DataFusion consumer path (not CAS/dataset-only) | **PARTIAL** | End-to-end gate on a pinned package + historian revision with logged timings and row counts |
| **H14** — measured p50/p95 against the table above | **PARTIAL** | Repeatable benchmark artifact (host class, revision, N runs) under `reports/` or CI job output |
| **Q06** — AppSec `rdflib` parse of **product** C3 TTL bytes | **PARTIAL** | Committed `scripts/fixtures/haystack_rdf/generated/c3_projection.ttl` (or CI-generated equivalent) + AppSec step running `pytest tests/fixtures/test_haystack_rdf_c3_projection.py -q` **without** invoking `cargo` |

Until `c3_projection.ttl` is committed, local pytest may fall back to `cargo run … haystack_c3_export_fixture`; that path is **not** wired in AppSec (no Rust build in the security-harness job).
