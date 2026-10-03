---
title: Haystack RDF C1 baseline audit
parent: Modeling
nav_order: 16
---

# C1 baseline audit (read-only)

Recorded for wave Haystack RDF **C1** (#998). Not a qualification pass.

| Item | Value |
| --- | --- |
| Baseline git | `68314631a1ff1fe19f70d73d574f0db6b242d9da` (master at branch point) |
| Synthetic fixtures | `scripts/fixtures/haystack_rdf/` |
| Maintainer BUILDING_100 audit inputs | **Not** committed; use synthetic fixtures only |

## Export baseline (native, not strict Haystack)

Traced exporters at baseline:

| Path | Finding |
| --- | --- |
| `edge/src/csv_ingest/data_model_ttl.rs` | Declares `@prefix hs:` but emits only `ofdd:*` types and properties |
| `frontend/web/src/api/dataModelTurtle.ts` | Same `hs:` prefix; no `ph:` or Haystack class IRIs in triples |
| `frontend/web/src/api/mappingApi.ts` | `openfdd_data_model_v1` includes diagnostics TTL omits |
| `services/central/src/routes.rs` | Package mapping + TTL routes; no `/api/model/sparql` on product central |

Independent audit reference (2026-09-22): large site TTL had thousands of
`ofdd:roleBinding` / `ofdd:unmappedColumn` triples and **zero** Haystack IRI
subjects despite the prefix — custom Open-FDD RDF, not `ofdd_haystack_projection_v1`.

## Diagnostics gap (JSON vs TTL)

Native JSON exports `ambiguous_roles`, `blockers`, `warnings`, and
`parent_ahu_source`. Package TTL exports role bindings, unmapped columns, and
confirmed parent edges only. Mapping quality issues visible in JSON disappear
from downloaded Turtle — HR-05 / HR-04 motivation for C3 projection reports.

## Gate 36

See [gate 36 gap list for C5](../operations/gate36_haystack_rdf_gap_list.md).

## Next waves

| Wave | Delivers |
| --- | --- |
| C2 | Versioned native metadata persistence |
| C3 | Strict `ofdd_haystack_projection_v1` serialization + tests |
| C4 | Model viewer + central SPARQL if scoped |
| C5 | Gate 36 + HR-12 evaluator integrity |
