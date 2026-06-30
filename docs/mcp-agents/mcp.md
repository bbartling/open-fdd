---
title: MCP setup
parent: MCP & Agents
nav_order: 1
---

# MCP setup

## Images

| Image | Use |
|-------|-----|
| `ghcr.io/bbartling/openfdd-edge-rust` | Bundled `openfdd-mcp` via `--entrypoint openfdd-mcp` |
| `ghcr.io/bbartling/openfdd-mcp` | Transitional slim MCP-only image |

## Edge entrypoint (preferred)

```bash
docker run --rm -i \
  -v ~/open-fdd/workspace:/var/openfdd/workspace \
  -e OPENFDD_API_URL=http://host.docker.internal:8080 \
  -e OPENFDD_JWT="$TOKEN" \
  --entrypoint openfdd-mcp \
  ghcr.io/bbartling/openfdd-edge-rust:latest
```

## Cursor `mcp.json` (illustrative)

```json
{
  "mcpServers": {
    "openfdd": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/home/user/open-fdd/workspace:/var/openfdd/workspace",
        "-e", "OPENFDD_JWT",
        "ghcr.io/bbartling/openfdd-mcp:latest"
      ],
      "env": { "OPENFDD_JWT": "<integrator JWT>" }
    }
  }
}
```

## Tool surface

MCP tools map to REST endpoints — ingest preflight, assignments, rules batch, commissioning import/export, health, reports. Discover via:

```http
GET /api/agent/tools
```

## Compose sidecar (optional)

```bash
docker compose -f docker/compose.edge.rust.yml --profile mcp-sidecar up -d openfdd-mcp
```
