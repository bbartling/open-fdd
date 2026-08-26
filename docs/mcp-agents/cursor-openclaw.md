---
title: Cursor & OpenClaw
parent: MCP & Agents
nav_order: 3
---

# Cursor & OpenClaw

## Cursor IDE

1. Bring up the stack: `./scripts/openfdd_stack_up.sh standalone` (or Railway private central)
2. Obtain an **operator** JWT: `POST /api/auth/login` with `{"username":"agent","password":"$OPENFDD_AGENT_PASSWORD"}`  
   (or admin bearer → `POST /api/auth/agent-token`). Do **not** put `OPENFDD_ADMIN_PASSWORD` in MCP config.
3. Configure the MCP server (`ghcr.io/bbartling/openfdd-mcp`) with `OPENFDD_API_BASE` → central and `OPENFDD_MCP_TOKEN` → that JWT
4. Use tools for health, assignments, CSV preflight, rules, reports

Railway: see [RAILWAY_DEPLOYMENT.md](../operations/RAILWAY_DEPLOYMENT.md) § Secure agent auth — secrets stay in Railway Variables; MCP stays private.

Open-FDD does **not** ship an in-dashboard chatbot. Connect Cursor to **`openfdd-mcp`** (stdio) — see [external agents examples](../examples/external-agents.md).

## OpenClaw on Raspberry Pi

OpenClaw agents on a fresh Pi bring up the stack from GHCR images — see
[Raspberry Pi edge](../quick-start/raspberry-pi-edge.html):

```text
ghcr.io/bbartling/openfdd-central:latest
ghcr.io/bbartling/openfdd-web
ghcr.io/bbartling/openfdd-fieldbus:latest
ghcr.io/bbartling/openfdd-mqtt:latest
```

Typical flow:

1. `./scripts/openfdd_stack_up.sh standalone` on the Pi
2. Validate with `./scripts/openfdd_health_check.sh`
3. Wire MCP with **agent** (operator) JWT, not admin password
4. Use agent tools for commissioning — never BACnet writes without approval

## Grounded workflows

| Task | MCP / API |
|------|-----------|
| CSV import | `openfdd_csv_import_preflight`, `/api/csv/import/execute` |
| Hourly CSV append | `openfdd_csv_package_append` → `POST /api/csv/import/package/append` (JWT + `confirm:true`) |
| Model bind | `/api/model/assignments/save` |
| Rule deploy | `/api/rules/batch`, `/api/fdd-rules/{id}/activate` |
| Site health | `/api/health`, `/api/dashboard/summary` |

Avoid speculative language — verify with health and historian plots before claiming faults are active.
