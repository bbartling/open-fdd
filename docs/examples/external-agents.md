---
title: External agent workflow
parent: MCP & Agents
nav_order: 4
---

# External AI agent workflow

Open-FDD does **not** include an embedded AI chatbot. Operators may use **external** agents — Codex CLI, Cursor, Rig (if MCP-capable), Claude Desktop, OpenClaw, or any MCP-compatible host. Those tools connect through the optional `openfdd-mcp` stdio server or the documented JWT REST API.

This keeps Open-FDD vendor-neutral, local-first, safe for OT networks, and independent of any model provider.

## Preferred workflow

1. Bring up the stack locally or on the LAN/VPN (`./scripts/openfdd_stack_up.sh standalone`), **or** a private Railway central (see [RAILWAY_DEPLOYMENT.md](../operations/RAILWAY_DEPLOYMENT.md)).
2. Confirm health: `curl -fsS http://127.0.0.1:8080/api/health` (or Railway private URL).
3. Obtain an **operator** JWT — prefer `username=agent` + `OPENFDD_AGENT_PASSWORD`, or admin `POST /api/auth/agent-token`. Never print or commit tokens; never use the admin password as the MCP credential.
4. Run `openfdd-mcp` **outside** the Open-FDD web UI (stdio JSON-RPC), with `OPENFDD_MCP_TOKEN` set to that JWT.
5. Connect your external agent to MCP or REST (`GET /api/agent/tools`).
6. Use **read** tools first.
7. Enable writes only with `OPENFDD_MCP_ALLOW_WRITES=1` and `confirm:true` on mutating tools.
8. Never perform BACnet writes without explicit human approval.

## Railway / remote deployments

Remote FDD AI assistance must use the same JWT model as LAN:

| Secret | Purpose |
| --- | --- |
| `OPENFDD_JWT_SECRET` | Signs JWTs (≥32 chars); required off-loopback |
| `OPENFDD_ADMIN_PASSWORD` | Browser admin UI + minting agent tokens |
| `OPENFDD_AGENT_PASSWORD` | Dedicated agent login → operator JWT for MCP/Cursor |

Keep central + MCP on Railway private networking. Public domain belongs on **web** only.

## Codex CLI (example)

If your Codex install supports MCP server configuration, point it at the same `openfdd-mcp` binary or Docker entrypoint documented in [mcp/README.md](../../mcp/README.md). Use integrator JWT in `OPENFDD_MCP_TOKEN`.

## Cursor (example)

```json
{
  "mcpServers": {
    "openfdd": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm", "--network", "host",
        "-e", "OPENFDD_API_BASE=http://127.0.0.1:8080",
        "-e", "OPENFDD_COMMISSION_BASE=http://127.0.0.1:9091",
        "-e", "OPENFDD_MCP_TOKEN",
        "ghcr.io/bbartling/openfdd-mcp:latest"
      ],
      "env": { "OPENFDD_MCP_TOKEN": "<JWT from login>" }
    }
  }
}
```

## Generic MCP host

- Transport: stdio JSON-RPC (MCP 2024-11-05)
- Image: slim `ghcr.io/bbartling/openfdd-mcp:<tag>`
- Auth: `OPENFDD_MCP_TOKEN` bearer JWT
- Writes: gated — see [mcp/INSTRUCTIONS.md](../../mcp/INSTRUCTIONS.md)

## Local / offline agents (Rig, scripts)

If a tool supports MCP or shell-driven REST workflows, use the same JWT + `/api/agent/tools` catalog. Open-FDD does not bundle Rig or any vendor SDK.

## What Open-FDD ships

| In product | External only | Not shipped |
|------------|---------------|-------------|
| REST API + JWT | Codex, Cursor, Claude, OpenClaw, … | In-dashboard chat panels |
| `openfdd-mcp` stdio server | Model routing / LLM runtime | `CURSOR_API_KEY` in edge stack |
| Deterministic CSV/FDD/Haystack tools | | |
| Human review on proposals | | |

See also [AGENTS.md](../../AGENTS.md) and [mcp/README.md](../../mcp/README.md).
