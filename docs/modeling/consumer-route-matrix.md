---
title: Data model consumer / route matrix
parent: Modeling
nav_order: 8
---

# Consumer / route matrix (DM-06)

Honest capability map for package model JSON/TTL, legacy commissioning RDF, and
SPARQL. Update when routes land. Tip authority: Wave S2 ADR
[`../architecture/ADR_data_model_graph.md`](../architecture/ADR_data_model_graph.md).

| Consumer | Surface | Auth | Product status (Wave S2) | Notes |
| --- | --- | --- | --- | --- |
| SPA Mapping | `GET /api/csv/import/package/mapping?building_id=` | JWT + building scope | **Shipped** | Inventory JSON; stamped types (DM-04); `parent_ahu` only when the package map names `parentAhu` |
| SPA Mapping TTL | `GET /api/csv/import/package/mapping/ttl?building_id=` | JWT + building scope | **Shipped** | Prefix `urn:openfdd:ns#`; dual TS/Rust exporters; skips `parent_ahu_source=inferred` |
| SPA Mapping export | browser download of same JSON/TTL | JWT | **Shipped** | Building membership checked; hub-root storage (see [tenant storage honesty](tenant-storage-honesty.md)) |
| Central package RDF dataset | `GET /api/csv/import/package/mapping/haystack-dataset?building_id=` | JWT + building scope | **Shipped (C4 H8)** | Derived from committed `semantic_meta` + pinned defs (`ofdd_haystack_central_dataset_v1`); not edge prototype graph |
| Central SPARQL | `POST /api/model/sparql` | JWT + building scope | **Shipped (C4 H9 templates)** | Server `query_id` templates → `ofdd_haystack_typed_bindings_v1`; free-form `query` rejected; consumers (H10+) still required to close #1002 |
| Central SPARQL catalog | `GET /api/model/sparql/predefined` | JWT | **Shipped (C4 H9)** | Lists template ids / SELECT bodies over package RDF |
| Legacy edge | edge model SPARQL (+ predefined) | JWT (edge) | **Legacy / edge path** | Prefix `https://open-fdd.dev/model#`; Oxigraph; not the package TTL dataset |
| MCP | `openfdd_model_sparql` / `_catalog` | JWT → `OPENFDD_API_BASE` | **Advertised; fails closed on 404/501** | Must not claim package TTL/dataset is the MCP query engine |
| Graph store (process) | in-process Oxigraph on edge | N/A | **Legacy** | Global `data/model/*` — not MT ACL ([DM-05 honesty](tenant-storage-honesty.md)) |
| Dataset registry | `GET/DELETE /api/datasets` | JWT + building scope | **Shipped** (3.5.31) | Foreign `building_id` → 403 |
| Session / roles | `/api/fdd/session-config` | JWT + building scope | **Shipped** | Wave O ACL |
| Model/ECM stress gate | `36_model_ecm_qualification.sh` | stress profile | **Wired (CI/smoke); FQ on S4** | See gate script + Wave S4 MEGA |
| Strict Haystack TTL | `GET /api/csv/import/package/mapping/haystack.ttl?building_id=` | JWT + building scope | **Shipped (C3)** | Profile [`haystack-rdf-profile.md`](haystack-rdf-profile.md); requires `semantic_meta.json` |
| Strict Haystack projection JSON | `GET /api/csv/import/package/mapping/haystack-projection?building_id=` | JWT + building scope | **Shipped (C3)** | Turtle + omission report (`ofdd_haystack_projection_report_v1`) |
| Native semantic meta JSON | `GET /api/csv/import/package/mapping/semantic-meta?building_id=` | JWT + building scope | **Shipped (C3)** | `openfdd_semantic_meta_v1` export; empty when absent |
| Haystack RDF C1/C3 fixtures | `scripts/fixtures/haystack_rdf/` | repo | **Shipped (docs/tests)** | Synthetic only; independent expected answers |

## Capability honesty rules

1. Central package SPARQL is template-only (`query_id`). Empty bindings are not a feature PASS; #1002 still needs H10+ consumers. Legacy edge SPARQL ≠ package dataset.
2. Downloaded package TTL / `haystack-dataset` (`urn:openfdd:…`) is the H8/H9 graph source; MCP must call central templates, not assume edge prototype SPARQL.
3. SCAFFOLD docs in `docs/mcp-agents/roles/package-mapping.md` stay labeled until tools are live against central.
4. Declaring `@prefix hs:` on native package TTL does **not** mean Haystack
   interoperability — see [JSON/RDF crosswalk](data-model-json-rdf-crosswalk.html).
5. Gate 36 evaluator gaps for Haystack qualification are tracked in
   [gate 36 gap list](../operations/gate36_haystack_rdf_gap_list.md) (C5).

## Smoke (operator)

```bash
TOKEN=…  # admin JWT
# Catalog + template bindings (free-form query → 400 rejected):
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$OPENFDD_API_BASE/api/model/sparql/predefined" | jq '.status,.queries|length'
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"building_id":"SITE","query_id":"fdd_role_candidates"}' \
  "$OPENFDD_API_BASE/api/model/sparql" | jq '.schema,.ok'
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$OPENFDD_API_BASE/api/csv/import/package/mapping/haystack-dataset?building_id=SITE"
```
