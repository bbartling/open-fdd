---
title: MCP setup
parent: MCP & Agents
nav_order: 1
---

# MCP setup

## Image

| Image | Use |
|-------|-----|
| `ghcr.io/bbartling/openfdd-mcp` | Slim Rust MCP stdio server; talks to central over `OPENFDD_API_BASE` |

## Run (stdio)

```bash
docker run --rm -i --network host \
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \
  -e OPENFDD_MCP_TOKEN="$TOKEN" \
  ghcr.io/bbartling/openfdd-mcp:latest
```

Inside the compose network, point at central directly:
`OPENFDD_API_BASE=http://central:8080`.

## Cursor `mcp.json` (illustrative)

```json
{
  "mcpServers": {
    "openfdd": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--network", "host",
        "-e", "OPENFDD_API_BASE=http://127.0.0.1:8080",
        "-e", "OPENFDD_MCP_TOKEN",
        "ghcr.io/bbartling/openfdd-mcp:latest"
      ],
      "env": { "OPENFDD_MCP_TOKEN": "<integrator JWT>" }
    }
  }
}
```

## Tool surface

MCP tools map to REST endpoints — ingest preflight, assignments, rules batch, commissioning import/export, health, reports. Discover via:

```http
GET /api/agent/tools
```

## Pull with the stack

```bash
./scripts/openfdd_stack_pull.sh mcp
```

MCP clients speak stdio JSON-RPC, so launch with `docker run -i` (above) rather
than a detached compose service. See [Build recipes](../operations/build-recipes.md).
