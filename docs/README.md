# Open-FDD documentation

Local-first HVAC fault detection on a **Rust edge** (Arrow historian, DataFusion SQL, React dashboard, Docker/GHCR).

## Start here

| Audience | Document |
|----------|----------|
| Operators | [quick-start/rust-edge-bootstrap.md](quick-start/rust-edge-bootstrap.md) |
| Developers | [deployment/local-dev.md](deployment/local-dev.md) |
| AI / MCP agents | [ai-agent/README.md](ai-agent/README.md) · [AI_AGENT_API.md](AI_AGENT_API.md) |
| API (OpenAPI stub) | [openapi.yaml](openapi.yaml) |

## Platform

| Topic | Document |
|-------|----------|
| Architecture | [architecture/overview.md](architecture/overview.md) |
| Drivers and FDD | [architecture/drivers-and-fdd.md](architecture/drivers-and-fdd.md) |
| Haystack integration | [integrations/haystack.md](integrations/haystack.md) |
| Model + SPARQL | [modeling/haystack_dashboard_model.md](modeling/haystack_dashboard_model.md) |
| Assignments | [ASSIGNMENT_MODEL.md](ASSIGNMENT_MODEL.md) |
| Future appliance (OS) | [../os/README.md](../os/README.md) |

## Operations

| Topic | Document |
|-------|----------|
| Backup / update / restore | [quick-start/rust-site-lifecycle.md](quick-start/rust-site-lifecycle.md) |
| Production TLS | [operations/production-caddy.md](operations/production-caddy.md) |
| Auth | [security/rust-edge-auth.md](security/rust-edge-auth.md) |

## Agents and MCP

| Topic | Document |
|-------|----------|
| Agent index | [ai-agent/README.md](ai-agent/README.md) |
| Session context | [ai-agent-context.md](ai-agent-context.md) |
| MCP tool contract | [agent/openfdd-mcp-tool-contract.md](agent/openfdd-mcp-tool-contract.md) |
| MCP setup | [../mcp/README.md](../mcp/README.md) |
| Safety boundaries | [security/agent-safety-boundaries.md](security/agent-safety-boundaries.md) |

## Verification

Checklists under [verification/](verification/) — run after bootstrap, driver changes, or releases.

## Agent safety (all docs)

See root [AGENTS.md](../AGENTS.md): never delete `workspace/`, never `docker compose down -v`, never print secrets.
