---
name: local-dev-orchestration
description: "Starts multi-process local dev for generated bridge, MCP, and Vite UI with shared data dir and agent bootstrap JSON. Use when deploy=local and operators need one command to run the stack."
---

# Local dev orchestration

## When to use / When not to use

Use on Windows (PowerShell), macOS, Linux, or WSL to launch only the processes the manifest selected.

Do not use for production bench deploy ([ansible-linux-bench-deploy](../ansible-linux-bench-deploy/SKILL.md)).

## Prerequisites

- Repo or workspace with generated `api/` and `dashboard/` trees.
- `OFDD_DESKTOP_DATA_DIR` pointing at `workspace/data` or `stack/local-data` equivalent.

## Quick start

Roles (compose as needed):

| Role | Process | Default port |
|------|---------|--------------|
| gateway | uvicorn bridge | 8765 |
| mcp | MCP RAG REST | 8090 |
| ui | `npm run dev` | 5173 |
| adapter | stdio MCP → REST | — |

LAN: set `OFDD_BRIDGE_HOST=0.0.0.0`, `OFDD_MCP_LISTEN_HOST=0.0.0.0`, Vite `--host 0.0.0.0`, `OFDD_CORS_ALLOW_PRIVATE_LAN=1`, public URLs in env.

Write `openfdd-agent-bootstrap.json` with bridge, MCP, UI bases and endpoint map (see codex skill).

## Verification

- `curl` bridge `/health`, MCP `/health`, open UI origin.

## Gotchas

- Rebuild doc index only if MCP skill included ([mcp-doc-retrieval](../mcp-doc-retrieval/SKILL.md)).
- Firewall ports 8765, 8090, 5173 for LAN.

See [references/REFERENCE.md](references/REFERENCE.md).
