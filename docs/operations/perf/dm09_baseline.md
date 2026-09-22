# DM-09 / PERF-1 — RDF projection baseline (Wave U W4)

**Status:** Soft-OPEN / PARTIAL — measure-first tip; not a PERF win claim.

## Budgets declared (product tip 3.5.45)

| Control | Value | Notes |
| --- | --- | --- |
| SPARQL SELECT materialization cap | `SPARQL_MAX_ROWS = 5000` (+1 probe) | Early break in `edge/src/model/rdf.rs::sparql_select` — does not alone bound join CPU |
| Projection version | `ofdd_haystack_projection_v1` | Declared in Turtle; `claimsLosslessJson false` |
| HTTP timeout | (route-dependent) | Not a RAM bound |

## What this tip shipped

1. Stop collecting unbounded SPARQL solutions before truncation (cap at `MAX_ROWS+1`).
2. Permanent unit coverage for projection honesty (DM-10 false-marker) + shared cap constant with `sparql.rs`.
3. This baseline table — full 1k/10k/100k point harness remains Soft-OPEN
   (requires isolated host / CI job with recorded RSS).

## How to extend (next tip)

```bash
# On a host authorized for cargo benches (not bensbench image builds):
cargo test -p open_fdd_edge_prototype rdf:: --lib
# Record wall/RSS for cold rebuild + warm SELECT on fixed fixtures into
# docs/operations/perf/dm09_<stamp>.json — then compare candidate vs this baseline.
```

Do not mark PERF-1 PASS without identical datasets, correct answers, and
baseline→candidate measurements.
