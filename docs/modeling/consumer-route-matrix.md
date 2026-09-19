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
| SPA Mapping | `GET /api/csv/import/package/mapping?building_id=` | JWT + building scope | **Shipped** | Inventory JSON; stamped types preferred (S5 DM-04) |
| SPA Mapping TTL | `GET /api/csv/import/package/mapping/ttl?building_id=` | JWT + building scope | **Shipped** | Prefix `urn:openfdd:ns#`; dual TS/Rust exporters (S5 parity) |
| SPA Mapping export | browser download of same JSON/TTL | JWT | **Shipped** | Building membership checked; identical IDs across tenants still S5 |
| Central SPARQL | `POST /api/model/sparql` | — | **Unavailable on central** | Not registered on product central router |
| Central SPARQL catalog | `GET /api/model/sparql/predefined` | — | **Unavailable on central** | — |
| Legacy edge | `POST /api/model/sparql` (+ predefined) | JWT (edge) | **Legacy / edge path** | Prefix `https://open-fdd.dev/model#`; Oxigraph; not the package TTL dataset |
| MCP | `openfdd_model_sparql` / `_catalog` | JWT → `OPENFDD_API_BASE` | **Advertised; fails closed if central 404** | Must not claim package TTL is the MCP query dataset |
| Graph store (process) | in-process Oxigraph on edge | N/A | **Legacy** | Global `data/model/*` paths are not multi-tenant ACL (S5 DM-05) |
| Dataset registry | `GET/DELETE /api/datasets` | JWT + building scope | **Shipped** (3.5.31) | Foreign `building_id` → 403 |
| Session / roles | `/api/fdd/session-config` | JWT + building scope | **Shipped** | Wave O ACL |

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
