# REST API reference (Rust edge)

Authoritative route list: `GET /api/agent/tools` on a running site. Prefer [AGENTS.md](../AGENTS.md) and [quick-start/rust-edge-bootstrap.md](quick-start/rust-edge-bootstrap.md) for install.

**Base URL:** `http://127.0.0.1:8080` (LAN only). **Auth:** Bearer JWT except where noted.

## Authentication

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/health` | none | Liveness |
| POST | `/api/auth/login` | none | Body: `{"username","password"}` → `token` / `access_token` |
| GET | `/api/auth/me` | JWT | Current principal |

Roles: `operator`, `integrator`, `agent`. Mutations on drivers, model import, rule activation, and field-bus writes require `integrator` or `agent` unless noted.

## Haystack model (RDF / SPARQL)

The Haystack grid is projected to Turtle and queried with **Oxigraph** (read-only SELECT).

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/model/haystack` | JWT | Raw Haystack grid JSON |
| GET | `/api/model/ttl` | JWT | Turtle export (`Accept: text/turtle`) |
| POST | `/api/model/sync-ttl` | integrator+ | Persist `workspace/data/model/data_model.ttl` |
| GET | `/api/model/sparql/predefined` | JWT | Catalog + default query |
| POST | `/api/model/sparql` | JWT | Body: `{"query":"<SPARQL SELECT>"}` → `bindings` |
| GET | `/api/model/sites` | JWT | Sites + active site |
| GET | `/api/model/sites/{id}/equipment` | JWT | Equipment for site |
| GET | `/api/model/tree` | JWT | Site-scoped equipment + points (SPARQL-backed) |
| GET | `/api/model/graph` | JWT | Network graph (equipment, feeds, points) |
| GET | `/api/model/assignments` | JWT | Driver → Haystack → FDD bindings |
| POST | `/api/model/assignments/save` | integrator+ | Save bindings |
| POST | `/api/model/haystack/import` | integrator+ | Import from Haystack driver |
| GET | `/api/dashboard/model-coverage` | JWT | Mapped / unmapped summary |

Example SPARQL:

```bash
curl -s -X POST http://127.0.0.1:8080/api/model/sparql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"PREFIX hs: <https://project-haystack.org/def/> PREFIX ofdd: <https://open-fdd.dev/model#> SELECT ?site ?dis WHERE { ?s a hs:Site . ?s ofdd:haystackId ?site . OPTIONAL { ?s hs:dis ?dis . } }"}'
```

Vocabulary: `hs:` = Project Haystack def; `ofdd:haystackId` = canonical Haystack ref string.

## Drivers

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/bacnet/driver/tree` | BACnet registry |
| POST | `/api/bacnet/read` | Read property |
| POST | `/api/bacnet/write` | integrator+; dry-run in prototype |
| GET | `/api/modbus/points` | Register map |
| POST | `/api/modbus/read` | Read registers |
| GET | `/api/haystack/status` | Gateway status (200 when disabled) |
| POST | `/api/haystack/read` | Read by ids or filter |
| POST | `/api/haystack/import` | Import into model grid |
| GET | `/api/json-api/sources` | JSON API sources |

Commission OT reads (host network): `http://127.0.0.1:9091` — see [architecture/drivers-and-fdd.md](architecture/drivers-and-fdd.md).

## FDD and historian

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/rules` | Rule catalog |
| POST | `/api/fdd-rules/builder-sql` | Draft SQL from inputs |
| POST | `/api/fdd-rules/{id}/test-sql` | Dry-run against historian |
| POST | `/api/fdd/run` | Run evaluation |
| GET | `/api/historian/query` | Arrow / DataFusion query |
| GET | `/api/faults` | Active faults |
| GET | `/api/building/status` | Public building summary (no JWT) |

## Agent and MCP

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/agent/tools` | Machine-readable tool manifest |
| GET | `/api/agent/manifest` | Agent metadata |
| GET | `/api/health/stack` | Bridge + sidecar health |

MCP sidecar: [mcp/README.md](../mcp/README.md) · [agent/openfdd-mcp-tool-contract.md](agent/openfdd-mcp-tool-contract.md)

## Safety

- Do not delete `workspace/` or run `docker compose down -v`.
- Do not log JWTs or `auth.env.local`.
- Field-bus writes require explicit human approval.
- Keep the edge on LAN / Tailscale, not the public internet.
