# Agent safety boundaries

Rules for **human operators**, **external AI agents** (Cursor, Codex, OpenClaw), and **future MCP** clients working with Open-FDD.

## Hard prohibitions

| Action | Why |
| --- | --- |
| `docker compose down -v` | Destroys named volumes / site state |
| Delete or wipe `workspace/` | Auth, historian, reports, driver configs |
| Delete backups, Feather/historian files without operator sign-off | Irrecoverable telemetry |
| Print or commit secrets (JWT, passwords, bcrypt, customer site details) | Credential leak |
| Expose bridge, dashboard, MCP, or Ollama on the public internet | Attack surface |
| BACnet/Modbus/Haystack **writes** or override clearing without explicit human approval | Life-safety / BAS integrity |
| Change live building behavior during doc-only / agent-architecture tasks | Scope separation |

## Network

- Bridge default: `127.0.0.1:8080` in compose templates
- Caddy profiles terminate TLS on LAN only when operators configure certs
- BACnet commission container uses `network_mode: host` by design — isolate OT VLANs
- Ollama (if used) stays on operator workstation or lab VLAN — not a bridge dependency

## Authentication

- Credentials live in `workspace/auth.env.local` (mode `600`)
- Agents obtain JWT via `POST /api/auth/login` — never embed long-lived tokens in repo
- Prefer **integrator** or **agent** role for automation; **operator** for read/export

## Safe automation scripts

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
./scripts/openfdd_322_prep_validate.sh
./scripts/openfdd_322_ghcr_validation.sh
```

Use isolated smoke/parity scripts with explicit env (device instance, profiles) — never hardcode bench IDs in production Rust/TypeScript.

## Model routing

| Class | Examples | Model tier |
| --- | --- | --- |
| **Simple** | fmt failure, one test red, 404 route, missing DOM selector | Worker / mini |
| **Complex** | RBAC bug, flaky multi-service smoke, deploy script change, OT write API | Thinking / orchestrator |

When uncertain, classify as **complex**.

## MCP (future)

- Phase 1 tools: read-only only ([openfdd-mcp-tool-contract.md](../agent/openfdd-mcp-tool-contract.md))
- Phase 2 mutations: require documented human approval ID
- MCP must not bypass RBAC already enforced on REST

## Reporting incidents

If an agent violates boundaries, stop automation, rotate credentials if exposure suspected, and file a GitHub issue with reproduction steps — no secrets in the issue body.

## See also

- [AGENTS.md](../../AGENTS.md)
- [../agent/openfdd-agent-architecture.md](../agent/openfdd-agent-architecture.md)
