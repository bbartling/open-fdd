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
| SPA Mapping | `GET /api/csv/import/package/mapping?building_id=` | JWT + building scope | **Shipped** | Inventory JSON; stamped types preferred (DM-04); inferred `parent_ahu` is proposal-only |
| SPA Mapping TTL | `GET /api/csv/import/package/mapping/ttl?building_id=` | JWT + building scope | **Shipped** | Prefix `urn:openfdd:ns#`; dual TS/Rust exporters; skips `parent_ahu_source=inferred` |
| SPA Mapping export | browser download of same JSON/TTL | JWT | **Shipped** | Building membership checked; hub-root storage (see [tenant storage honesty](tenant-storage-honesty.md)) |
| Central SPARQL | `POST /api/model/sparql` | — | **Unavailable on central** | Not registered on product central router |
| Central SPARQL catalog | `GET /api/model/sparql/predefined` | — | **Unavailable on central** | — |
| Legacy edge | `POST /api/model/sparql` (+ predefined) | JWT (edge) | **Legacy / edge path** | Prefix `https://open-fdd.dev/model#`; Oxigraph; not the package TTL dataset |
| MCP | `openfdd_model_sparql` / `_catalog` | JWT → `OPENFDD_API_BASE` | **Advertised; fails closed if central 404** | Must not claim package TTL is the MCP query dataset |
| Graph store (process) | in-process Oxigraph on edge | N/A | **Legacy** | Global `data/model/*` — not MT ACL ([DM-05 honesty](tenant-storage-honesty.md)) |
| Dataset registry | `GET/DELETE /api/datasets` | JWT + building scope | **Shipped** (3.5.31) | Foreign `building_id` → 403 |
| Session / roles | `/api/fdd/session-config` | JWT + building scope | **Shipped** | Wave O ACL |
| Model/ECM stress gate | `36_model_ecm_qualification.sh` | stress profile | **Wired (CI/smoke); FQ on S4** | See gate script + Wave S4 MEGA |

## Capability honesty rules

1. If central returns 404 for SPARQL tools, report **unavailable** — never PASS via empty result lists.
2. Downloaded package TTL (`urn:openfdd:ns#`) is **not** automatically the same dataset MCP SPARQL queries.
3. SCAFFOLD docs in `docs/mcp-agents/roles/package-mapping.md` stay labeled until tools are live against central.

## Smoke (operator)

```bash
TOKEN=…  # admin JWT
# Expect 404 (or connection error) on product hub until S5 adds the route:
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"SELECT * WHERE { ?s ?p ?o } LIMIT 1"}' \
  "$OPENFDD_API_BASE/api/model/sparql"
```
