---
title: Gate 36 gaps for Haystack RDF C5
parent: Operations
nav_order: 95
---

# Gate 36 — gap list for Haystack RDF C5 (#1003)

**Status:** C1 baseline (#998). These gaps are **documented, not fixed** in C1.
C5 owns evaluator hardening (HR-12).

Source script: `scripts/nightly-ot-bench/36_model_ecm_qualification.sh`  
Manifest: `scripts/qualification/write_manifest.py`  
Rollout requirements: [`openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md`](../../openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md)

| Gap ID | Observation | Risk | C5 acceptance direction |
| --- | --- | --- | --- |
| G36-01 | `model.ecm.mapping_own` PASS on HTTP 200 without nonempty inventory assert | Empty site greenwashes model readiness | Require expected equipment count or fixture hash when gate runs with `OPENFDD_MODEL_FIXTURE=…` |
| G36-02 | Tenant B login only; no check that B can read **own** building inventory | B creds valid but model empty → false confidence | Add `model.ecm.mapping_own_b` with positive control on `BUILDING_B` |
| G36-03 | No reverse probe **B→A** foreign deny symmetry beyond A→B | One-direction ACL miss | Mirror foreign mapping/TTL deny for `TOK_B` → `BUILDING_A` |
| G36-04 | Foreign 404 without owner-positive existence control | 404 ambiguous (missing vs denied) | Admin/owner JWT proves target building exists before deny test |
| G36-05 | ~~SPARQL check POSTs **no query body**~~ **H13:** catalog AVAILABLE + free-form rejected | Was non-semantic PASS | `model.ecm.sparql_catalog_available` + `model.ecm.sparql_freeform_rejected` |
| G36-06 | SPARQL fallback treats some non-404 codes as PASS without semantic proof | Transport errors masked | Classify 401/5xx as ERROR; require body schema when 200 |
| G36-07 | ECM path only checks `import open_fdd.ecm_engineering` when offline flag set | Import ≠ adapter math | Run `tests/ecm_engineering` adapter fixture with model inputs (HR-08) |
| G36-08 | Gate verdict `ok:true` while note says FQ owned elsewhere | Rollup confusion | Separate **smoke** vs **qualification** manifest profiles |
| G36-09 | `write_manifest.py` dimension rollup can PASS security bucket while individual gates BLOCKED | HR-12 false qualification | Required-set must treat BLOCKED on `36_model_ecm_qualification` as non-qualifying when listed required |
| G36-10 | No permanent negative fixtures (malformed TTL, stale hash, duplicate check id) wired to gate 36 | Evaluator drift | Add `tests/qualification/` broken-artifact cases per HR-12 |

## Stable check IDs (today)

Existing IDs to preserve when extending (do not rename to imply Haystack PASS):

- `model.ecm.login`
- `model.ecm.mapping_own`
- `model.ecm.dm04_stamp_provenance`
- `model.ecm.mapping_foreign_denied`
- `model.ecm.mapping_ttl_foreign_denied`
- `model.ecm.sparql_unavailable`
- `model.ecm.sparql_catalog_available`
- `model.ecm.sparql_freeform_rejected`
- `model.ecm.ecm_adapter_import`

## C1 evidence

Reproduced against source at C1 branch baseline; see
[`docs/modeling/haystack-rdf-c1-baseline-audit.md`](../modeling/haystack-rdf-c1-baseline-audit.md).
