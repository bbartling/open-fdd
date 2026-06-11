---
title: Workspace env files
parent: Appendix
nav_order: 4
---

# Workspace env files

All live under `workspace/`. Copy from `*.example` templates; committed `*.local` files are gitignored.

| File | Loaded by | Purpose |
|------|-----------|---------|
| `auth.env.local` | `run_local.sh`, Docker compose, Ansible | JWT secret (`OFDD_AUTH_SECRET`), integrator/operator/agent passwords, `OFDD_AUTH_DISABLED` for localhost dev only |
| `data.env.local` | `run_local.sh`, bridge, feather maintain | Feather historian caps (`OFDD_FEATHER_*`), audit/error log rotation (`OFDD_LOG_*`), BACnet discovery mutation toggle |
| `json_api.env.local` | bridge, Ansible edge sync | API keys for JSON API driver `${ENV:VAR}` substitution (e.g. `OPENWEATHER_API_KEY`) |
| `ollama.env.local` | `run_local.sh`, bridge | Ollama base URL, model name, RAM tier, GPU mode, timeouts — see [Ollama and analytics]({% link operator-bridge/ollama-analytics.md %}) |
| `mcp.env.local` | `run_local.sh`, MCP sidecar | Enable MCP RAG REST (`OFDD_MCP_*`), index path |
| `caddy.env.local` | `run_local.sh`, Ansible edge | Reverse proxy mode (`http` / `tls` / `off`), TLS CN, port overrides |
| `pentest.env.local` | `pentest_production_stack.sh` | Production-like LAN scan stack: CORS, auth, passive BACnet defaults |

## Ansible / edge extras

| Path | Purpose |
|------|-------|
| `infra/ansible/secrets/<host>.env.local` | SSH deploy credentials, GHCR pull tokens, site-specific BACnet bind — maintainers only |

## Related docs

- [Secrets and auth]({% link security/secrets-auth.md %}) — required production variables
- [Logging and audit]({% link ops/logging.md %}) — `OFDD_LOG_*` detail
- [JSON API driver]({% link drivers/json-api.md %}) — `${ENV:VAR}` pattern
- [Configuration reference]({% link appendix/configuration.md %}) — bridge runtime flags not in env files
