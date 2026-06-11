---
name: openfdd-mcp-server
description: "Open-FDD FastMCP server — edge and portfolio modes, bridge tools, doc RAG, human-approved writes."
---

# Open-FDD MCP server

## When to use

- Connect Cursor, Claude Desktop, Codex CLI, or OpenClaw to Open-FDD
- **Edge mode:** MCP on bensserver or analyst workstation calling local bridge (`OPENFDD_BRIDGE_BASE_URL`)
- **Portfolio mode:** central MCP with `portfolio/sites.json` over Tailscale

Acme edge (`enable_mcp: false`) has **no** MCP container — use portfolio MCP against `http://100.122.106.124`.

## Run locally

```bash
pip install -r workspace/mcp_server/requirements.txt
export PYTHONPATH=workspace:workspace/api
export OPENFDD_BRIDGE_BASE_URL=http://127.0.0.1:8765
export OFDD_MCP_MODE=edge
python -m mcp_server.run   # streamable-http on 127.0.0.1:8090
```

Stdio (IDE):

```bash
export OFDD_MCP_TRANSPORT=stdio
python -m mcp_server.run
```

Docker dev: `mcp-rag` service — legacy REST `/tools/search_docs` + MCP `/mcp`.

## Safety

- `human_approved=true` required for `save_rule`, `apply_fdd_tuning`, `run_fdd_batch`
- MCP never writes BACnet controllers — bridge APIs only
- Default bind `127.0.0.1`; expose LAN/Tailscale explicitly

See `docs/ai/mcp-server.md`.
