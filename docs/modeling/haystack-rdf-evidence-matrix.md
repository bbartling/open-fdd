---
title: Haystack RDF evidence matrix (C1)
parent: Modeling
nav_order: 17
permalink: /modeling/haystack-rdf-evidence-matrix.html
---

# Haystack RDF — evidence matrix (reconciled C1)

Tracks HR-01–HR-12 against wave C1–C6. **Do not close Soft-OPEN S5 rows** here;
this table adds Haystack-track ownership and C1 artifacts.

Historical S5 matrix: in-repo plan
`.cursor/plans/wave_s_data_model_evidence.md` (not modified by C1 PR).

| Req | Summary | Wave | C1 artifact | Status |
| --- | --- | --- | --- | --- |
| HR-02 | Identity / encoding | C1 | Profile § IRIs; fixtures `expected_c1_answers.json` | **SPEC** (policy locked) |
| HR-03 | Haystack semantics | C3 | Profile + pinned `ph` defs | **BLOCKED** on C3 |
| HR-04 | Projection fidelity | C3 | Crosswalk + baseline audit | **PARTIAL** (native only) |
| HR-05 | Mapping quality / uncertainty | C1 | Synthetic ambiguous/missing-parent fixtures | **FIXTURE** |
| HR-12 | Evaluator integrity | C5 | [Gate 36 gap list](../operations/gate36_haystack_rdf_gap_list.html) | **GAP LIST** |
| DM-09 | SPARQL scale / perf | S5 | Unchanged — **PARTIAL** (cap only) | Soft-OPEN |
| DM-10 | Projection honesty | S5/C1 | Profile name aligns with `rdf-vocabulary.md` narrow PASS | **PARTIAL** — full crosswalk in C1 docs, strict export still C3 |
| JSON-PARITY | Field crosswalk | C1 | [data-model-json-rdf-crosswalk.md](data-model-json-rdf-crosswalk.html) | **DOCS** (not isomorphism tests) |
| SPARQL-SEM | Central graph queries | C4 | Consumer matrix: unavailable | Soft-OPEN |
| STRESS-GATE | Gate 36 qualification | C5 | Gap list G36-01…G36-10 | Soft-OPEN |

**Honesty:** C1 does not bump `VERSION`, does not claim GHCR tip acceptance, and
does not mark HR-03/04 PASS.
