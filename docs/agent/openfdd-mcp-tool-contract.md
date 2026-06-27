# Open-FDD MCP tool contract (draft)

**Status:** Design for a future `openfdd-mcp` service (`SERVICE_MODE=mcp`). Not required for Open-FDD 3.2.x core runtime.

**Principles:**

1. **Read-first** — default tool set is observability and export only.
2. **JWT inherit** — MCP server uses operator-supplied bearer token; no embedded secrets.
3. **LAN/local bind** — listen on `127.0.0.1` or site VLAN; never public internet.
4. **Human approval** — field-bus writes, rule activation, restore, and override clearing require an explicit approval record (out of band from MCP auto-invoke).

## Tool catalog (phase 1 — read-only)

| Tool ID | REST mapping | Roles | Notes |
| --- | --- | --- | --- |
| `health.get` | `GET /api/health` | public | Liveness |
| `stack.status` | `GET /api/health/stack` | JWT | Bridge + sidecar summary |
| `drivers.bacnet.tree` | `GET /api/bacnet/driver/tree` | JWT | Device/point registry |
| `drivers.bacnet.override_scan_export` | `GET /api/bacnet/overrides/export` | operator+ | CSV attachment |
| `drivers.bacnet.overrides_summary` | `GET /api/bacnet/overrides/summary` | operator+ | Scan metadata |
| `drivers.modbus.points` | `GET /api/modbus/points` | JWT | Register map |
| `drivers.haystack.status` | `GET /api/haystack/status` | JWT | Gateway config redacted |
| `drivers.haystack.tree` | `GET /api/haystack/driver/tree` | JWT | Normalized points |
| `drivers.haystack.nav` | `POST /api/haystack/nav` | JWT | Body: `{ "navId": "..." }` |
| `drivers.haystack.read` | `POST /api/haystack/read` | JWT | Body: `{ "ids": [...] }` or filter |
| `rules.sql.validate` | `POST /api/fdd-rules/{id}/test-sql` | integrator+ | Dry-run SQL against historian |
| `rules.list` | `GET /api/rules` | JWT | Catalog |
| `model.export` | `GET /api/model/haystack` + assignments | JWT | Haystack grid snapshot |
| `model.import_dry_run` | `POST /api/model/haystack/import` with `dry_run: true` | integrator+ | **Proposed:** no persist until approved |
| `reports.rcx.generate` | `POST /api/reports/from-validation-run` | integrator+ | Rust PDF pipeline |
| `reports.list` | `GET /api/reports` | JWT | Draft metadata |
| `agent.tools` | `GET /api/agent/tools` | JWT | Discovery |

Role shorthand: `operator+` = operator, integrator, or agent per existing RBAC.

## Phase 2 — gated mutations (approval required)

These tools MUST NOT be callable without a documented approval artifact (ticket ID, operator ACK, or signed one-time token):

| Tool ID | REST mapping | Risk |
| --- | --- | --- |
| `rules.activate` | `POST /api/fdd-rules/{id}/activate` | Live fault detection |
| `model.assignments.save` | `POST /api/model/assignments` | Binds OT to FDD |
| `site.restore` | restore scripts / backup import | Data loss risk |
| `bacnet.write_property` | `POST /api/bacnet/write` | **Field bus write** |
| `bacnet.clear_overrides` | override clear routes | **BAS intervention** |
| `modbus.write` | Modbus write APIs | **Field bus write** |
| `haystack.point_write` | `POST /api/haystack/write` | **Station write** |
| `control.execute` | CDL execute (if added) | **Control** |

Default MCP policy: **deny all phase 2** unless `OPENFDD_MCP_ALLOW_WRITES=1` **and** per-call `approval_id` matches server-side allowlist.

## Forbidden (never expose via MCP)

- Raw `workspace/auth.env.local` or password hashes
- Unauthenticated bridge on `0.0.0.0` without Caddy/TLS site policy
- `docker compose down -v`, `docker volume prune`
- Bulk delete of `workspace/` historian/feather data without backup verification

## Error shape

Tools return JSON aligned with bridge responses:

```json
{ "ok": false, "error": "insufficient role", "tool": "drivers.bacnet.tree" }
```

## Implementation notes

- Model after read-only patterns in [rusty-bacnet-mcp](https://github.com/jscott3201/rusty-bacnet-mcp) (community) — separate binary, stdio or SSE transport.
- Reuse `GET /api/agent/tools` manifest until MCP server ships.
- Issue #402 proposed `open-fdd-mcp` as a **separate future task** — do not block edge releases on MCP.

## Related

- [openfdd-agent-architecture.md](openfdd-agent-architecture.md)
- [../security/agent-safety-boundaries.md](../security/agent-safety-boundaries.md)
