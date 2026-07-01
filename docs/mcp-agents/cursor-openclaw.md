---
title: Cursor & OpenClaw
parent: MCP & Agents
nav_order: 3
---

# Cursor & OpenClaw

## Cursor IDE

1. Bootstrap edge: `openfdd_rust_edge_bootstrap.sh --start`
2. Obtain JWT: `POST /api/auth/login` with integrator credentials
3. Configure MCP server pointing at `openfdd-mcp` or edge entrypoint
4. Use tools for health, assignments, CSV preflight, rules, reports

Open-FDD does **not** ship an in-dashboard chatbot. Connect Cursor to **`openfdd-mcp`** (stdio) — see [external agents examples](../examples/external-agents.md).

## OpenClaw on Raspberry Pi

OpenClaw agents on a fresh Pi should use **GHCR pull-only** deploy — not a source clone on the device:

```text
ghcr.io/bbartling/openfdd-edge-rust:latest
```

Typical flow:

1. Run bootstrap script on the Pi
2. Validate with `openfdd_rust_edge_validate.sh`
3. Wire MCP with integrator JWT
4. Use agent tools for commissioning — never BACnet writes without approval

## Grounded workflows

| Task | MCP / API |
|------|-----------|
| CSV import | `openfdd_csv_import_preflight`, `/api/csv/import/execute` |
| Model bind | `/api/model/assignments/save` |
| Rule deploy | `/api/rules/batch`, `/api/fdd-rules/{id}/activate` |
| Site health | `/api/health`, `/api/dashboard/summary` |

Avoid speculative language — verify with health and historian plots before claiming faults are active.
