# External AI agent workflow

Open-FDD does **not** include an embedded AI chatbot. Operators may use **external** agents — Codex CLI, Cursor, Rig (if MCP-capable), Claude Desktop, OpenClaw, or any MCP-compatible host. Those tools connect through the optional `openfdd-mcp` stdio server or the documented JWT REST API.

This keeps Open-FDD vendor-neutral, local-first, safe for OT networks, and independent of any model provider.

## Preferred workflow

1. Start Open-FDD edge locally or on the LAN/VPN (`openfdd_rust_edge_bootstrap.sh --start`).
2. Confirm health: `curl -fsS http://127.0.0.1:8080/api/health`.
3. Obtain an integrator or agent JWT (never print or commit tokens).
4. Run `openfdd-mcp` **outside** the Open-FDD web UI (stdio JSON-RPC).
5. Connect your external agent to MCP or REST (`GET /api/agent/tools`).
6. Use **read** tools first.
7. Enable writes only with `OPENFDD_MCP_ALLOW_WRITES=1` and `confirm:true` on mutating tools.
8. Never perform BACnet writes without explicit human approval.

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
        "--entrypoint", "openfdd-mcp",
        "-e", "OPENFDD_API_BASE=http://127.0.0.1:8080",
        "-e", "OPENFDD_COMMISSION_BASE=http://127.0.0.1:9091",
        "-e", "OPENFDD_MCP_TOKEN",
        "ghcr.io/bbartling/openfdd-edge-rust:latest"
      ],
      "env": { "OPENFDD_MCP_TOKEN": "<JWT from login>" }
    }
  }
}
```

## Generic MCP host

- Transport: stdio JSON-RPC (MCP 2024-11-05)
- Binary: `/usr/local/bin/openfdd-mcp` inside `openfdd-edge-rust`, or slim `ghcr.io/bbartling/openfdd-mcp:<tag>`
- Auth: `OPENFDD_MCP_TOKEN` bearer JWT
- Writes: gated — see [mcp/INSTRUCTIONS.md](../../mcp/INSTRUCTIONS.md)

## Local / offline agents (Rig, scripts)

If a tool supports MCP or shell-driven REST workflows, use the same JWT + `/api/agent/tools` catalog. Open-FDD does not bundle Rig or any vendor SDK.

## What Open-FDD ships

| In product | External only |
|------------|----------------|
| REST API + JWT | Codex, Cursor, Claude, OpenClaw, … |
| `openfdd-mcp` stdio server | Model routing / LLM runtime |
| Deterministic CSV/FDD/Haystack tools | In-dashboard chat panels |
| Human review on proposals | `CURSOR_API_KEY` in edge stack |

See also [AGENTS.md](../../AGENTS.md) and [mcp/README.md](../../mcp/README.md).
