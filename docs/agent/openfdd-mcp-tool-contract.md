---
title: MCP tool contract
parent: External agents
nav_order: 5
---

# MCP tool contract

**Server:** `openfdd-mcp` · **Image:** `ghcr.io/bbartling/openfdd-mcp` · **Setup:** [mcp/README.md](../../mcp/README.md)

Read-first sidecar. JWT via `OPENFDD_MCP_TOKEN`. Bind `127.0.0.1` or site VLAN only.

## Principles

1. **Read-first** — observability and export by default.
2. **JWT inherit** — operator supplies bearer token; no embedded secrets.
3. **Human approval** — writes, rule activation, restore, and field-bus tools require explicit operator ACK (phase 2).

BACnet, Haystack wire, bench topology, and driver-status discovery are not in default 4.0 `tools/list`. Calling `openfdd_haystack_status`, `openfdd_haystack_test`, `openfdd_haystack_read`, `openfdd_bacnet_whois`, `openfdd_bacnet_read`, `openfdd_driver_status`, `openfdd_bench_topology`, or `driver_poll_status` returns a retired error and points at `archive/ot-edge`. Semantic SPARQL tools stay. Scoped provider tools `openfdd_provider_health` and `openfdd_provider_sites` stay. `openfdd_provider_sites` reports each NF site's `transport` (`rest` for portal HTTPS, `grpc` for LAN gRPC).

## Implemented tools (stdio)

| Tool | REST | Auth |
|------|------|------|
| `openfdd_health` | `GET /api/health` | none |
| `openfdd_provider_health` | `GET /api/providers/health` | JWT |
| `openfdd_provider_sites` | `GET /api/providers/sites` | JWT |
| `openfdd_model_sparql_catalog` | `GET /api/model/sparql/predefined` | JWT |
| `openfdd_model_sparql` | `POST /api/model/sparql` | JWT |
| `openfdd_model_sites` | `GET /api/model/sites` | JWT |
| `openfdd_model_coverage` | `GET /api/dashboard/model-coverage` | JWT |
| `openfdd_csv_import_preview` | `POST /api/csv/import/preview` (path/base64/multipart) | JWT |
| `openfdd_csv_import_plan` | `POST /api/csv/import/plan` | JWT |
| `openfdd_ingest_contract` | `GET /api/ingest/contract` | none |
| `openfdd_csv_import_preflight` | `POST /api/csv/import/preflight` | JWT |
| `openfdd_csv_workbench_quality` | `POST /api/csv-workbench/quality` | JWT |
| `openfdd_model_commissioning_export` | `GET /api/model/commissioning-export` | JWT |
| `openfdd_model_commissioning_import` | `POST /api/model/commissioning-import` | JWT + write gate |
| `openfdd_csv_fusion_preview` | `GET /api/csv/import/sessions/{id}/fusion-preview` | JWT |
| `openfdd_csv_import_execute` | `POST /api/csv/import/execute` | JWT + write gate + preflight pass |
| `openfdd_csv_package_append` | `POST /api/csv/import/package/append` | JWT + write gate + `confirm:true` |
| `openfdd_historian_query` | `GET/POST /api/historian/query` | JWT |
| `openfdd_fdd_rules_list` | `GET /api/fdd-rules` | JWT |
| `openfdd_fdd_rule_test_sql` | `POST /api/fdd-rules/{id}/test-sql` | JWT |
| `openfdd_rules_batch` | `POST /api/rules/batch` | JWT + write gate |
| `openfdd_fdd_rules_save` | `POST /api/fdd-rules` | JWT + write gate |
| `openfdd_fdd_rules_activate` | `POST /api/fdd-rules/{id}/activate` | JWT + write gate |
| `openfdd_reports_from_fdd_sql_run` | `POST /api/reports/from-fdd-sql-run` | JWT + write gate |
| `openfdd_integration_smoke` | Composite playbook | JWT (+ write gate if confirm) |
| `openfdd_fdd_run` | `POST /api/fdd/run` | JWT + write gate |
| `openfdd_model_assignments_save` | `POST /api/model/assignments/save` | JWT + write gate |
| `openfdd_reports_draft` | `POST /api/reports/draft` | JWT + write gate |
| `openfdd_reports_patch` | `PATCH /api/reports/{id}` | JWT + write gate |
| `openfdd_reports_render_pdf` | `POST /api/reports/{id}/render/pdf` | JWT + write gate |

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
| BACnet tree | retired | `archive/ot-edge` (not default 4.0 discovery) |
| Test SQL rule | POST | `/api/fdd-rules/{id}/test-sql` |
| Stack health | GET | `/api/health/stack` |

## Phase 2 — write tools (gated)

Requires **`OPENFDD_MCP_ALLOW_WRITES=1`** and **`confirm: true`** on each tool call:

| Tool | REST | Risk |
|------|------|------|
| `openfdd_csv_import_execute` | `POST /api/csv/import/execute` | Timescale historian write (preflight pass required) |
| `openfdd_model_commissioning_import` | `POST /api/model/commissioning-import` | Model + rules import |
| `openfdd_rules_batch` | `POST /api/rules/batch` | Run saved FDD rules |
| `openfdd_fdd_rules_save` | `POST /api/fdd-rules` | Save SQL rule |
| `openfdd_fdd_rules_activate` | `POST /api/fdd-rules/{id}/activate` | Activate rule |
| `openfdd_reports_from_fdd_sql_run` | `POST /api/reports/from-fdd-sql-run` | PDF from SQL run |
| `openfdd_fdd_run` | `POST /api/fdd/run` | Live FDD evaluation (ad-hoc SQL) |
| `openfdd_model_assignments_save` | `POST /api/model/assignments/save` | Model binding |
| `openfdd_reports_draft` | `POST /api/reports/draft` | Report create |
| `openfdd_reports_patch` | `PATCH /api/reports/{id}` | Report edit |
| `openfdd_reports_render_pdf` | `POST /api/reports/{id}/render/pdf` | PDF output |
| Rule activation | `POST /api/fdd-rules/{id}/activate` | Live FDD (REST only — not in MCP yet) |
| BACnet write | `POST /api/bacnet/write` | Field bus |
| Haystack write | `POST /api/haystack/write` | Station write |
| Site restore | backup/restore scripts | Data loss |

## Package / CSV ingest notes

- Package import expects RFC3339 `timestamp_utc` (`Z` or `+00:00`) and sibling Haystack maps (`points` / `column_roles`). Analytics POSTs (`/api/analytics/*`, health matrices, RCx) run **after** mapping.
- Haystack sidecar `"equip": "<string>"` is device metadata; nested package maps use object `equip`/`equipment`/`devices`.
- Empty analytics after import usually mean missing roles in the zip, not a broken MCP tool. Authoring: [`PACKAGE_AUTHORING.md`](PACKAGE_AUTHORING.md).

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
