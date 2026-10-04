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
