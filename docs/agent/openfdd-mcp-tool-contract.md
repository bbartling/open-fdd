# MCP tool contract

**Server:** `openfdd-mcp` · **Image:** `ghcr.io/bbartling/openfdd-mcp` · **Setup:** [mcp/README.md](../../mcp/README.md)

Read-first sidecar. JWT via `OPENFDD_MCP_TOKEN`. Bind `127.0.0.1` or site VLAN only.

## Principles

1. **Read-first** — observability and export by default.
2. **JWT inherit** — operator supplies bearer token; no embedded secrets.
3. **Human approval** — writes, rule activation, restore, and field-bus tools require explicit operator ACK (phase 2).

## Implemented tools (stdio)

| Tool | REST | Auth |
|------|------|------|
| `openfdd_health` | `GET /api/health` | none |
| `openfdd_driver_status` | Bundle: health, haystack/modbus/bacnet/json status | JWT |
| `openfdd_bench_topology` | Env `OPENFDD_BENCH_TOPOLOGY_FILE` or doc pointer | — |
| `openfdd_haystack_status` | `GET /api/haystack/status` | JWT |
| `openfdd_haystack_test` | `POST /api/haystack/test` | JWT |
| `openfdd_haystack_read` | `POST /api/haystack/read` | JWT |
| `openfdd_bacnet_read` | Commission `POST /api/bacnet/read` | JWT |
| `openfdd_model_sparql_catalog` | `GET /api/model/sparql/predefined` | JWT |
| `openfdd_model_sparql` | `POST /api/model/sparql` | JWT |
| `openfdd_model_sites` | `GET /api/model/sites` | JWT |
| `openfdd_model_coverage` | `GET /api/dashboard/model-coverage` | JWT |

### `openfdd_model_sparql`

Arguments:

```json
{ "query": "PREFIX hs: <...> SELECT ?site ?dis WHERE { ... }" }
```

Returns bridge JSON: `{ "ok", "bindings", "row_count", "query_engine": "sparql" }`. Only SELECT allowed; INSERT/DELETE rejected.

## REST mappings (agents without MCP)

Use the same JWT against the bridge directly — see [AI_AGENT_API.md](../AI_AGENT_API.md).

| Intent | Method | Path |
|--------|--------|------|
| Tool manifest | GET | `/api/agent/tools` |
| Haystack grid | GET | `/api/model/haystack` |
| SPARQL | POST | `/api/model/sparql` |
| Assignments | GET | `/api/model/assignments` |
| BACnet tree | GET | `/api/bacnet/driver/tree` |
| Test SQL rule | POST | `/api/fdd-rules/{id}/test-sql` |
| Stack health | GET | `/api/health/stack` |

## Phase 2 — gated (not in MCP by default)

Requires `OPENFDD_MCP_ALLOW_WRITES=1` and per-call approval record:

| Tool | REST | Risk |
|------|------|------|
| Rule activation | `POST /api/fdd-rules/{id}/activate` | Live FDD |
| Save assignments | `POST /api/model/assignments/save` | OT binding |
| BACnet write | `POST /api/bacnet/write` | Field bus |
| Haystack write | `POST /api/haystack/write` | Station write |
| Site restore | backup/restore scripts | Data loss |

## Forbidden

- Exposing `auth.env.local`, password hashes, or JWTs in tool output
- `docker compose down -v`, bulk `workspace/` delete without verified backup
- Public `0.0.0.0` bridge without TLS policy

## Errors

```json
{ "ok": false, "error": "insufficient role", "tool": "openfdd_model_sparql" }
```

## Related

- [bench-driver-setup-wsl-agent.md](bench-driver-setup-wsl-agent.md)
- [openfdd-agent-architecture.md](openfdd-agent-architecture.md)
- [../security/agent-safety-boundaries.md](../security/agent-safety-boundaries.md)
