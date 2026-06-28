# openfdd-mcp

Read-first [Model Context Protocol](https://modelcontextprotocol.io/) server for Open-FDD Rust edge. Proxies JWT-authenticated REST calls to `openfdd-bridge` and commission BACnet reads.

**Image:** `ghcr.io/bbartling/openfdd-mcp`

## After a Docker / GHCR site update

`openfdd_rust_site_update.sh` updates the **edge stack only**. MCP is opt-in — pull and wire it **after** the edge is healthy, using the **same tag** as the edge (`OPENFDD_IMAGE_TAG`, e.g. `3.2.3`).

```bash
cd ~/open-fdd
export OPENFDD_COMPOSE_ROOT="$PWD"
export OPENFDD_IMAGE_TAG=3.2.3

# Pull MCP image (optional — docker run will pull if missing)
docker compose -f docker/compose.edge.rust.yml --profile mcp-sidecar pull openfdd-mcp

# JWT for bridge REST (integrator or agent role)
source scripts/openfdd_auth_lib.sh
INTEGRATOR_PW="$(openfdd_auth_plaintext_password workspace/auth.env.local integrator)"
export OPENFDD_MCP_TOKEN="$(
  curl -s -X POST http://127.0.0.1:8080/api/auth/login \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token'
)"
```

**Cursor (stdio via Docker)** — MCP speaks JSON-RPC on stdin/stdout, not HTTP:

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
        "ghcr.io/bbartling/openfdd-mcp:3.2.3"
      ],
      "env": {
        "OPENFDD_MCP_TOKEN": "<JWT from login above>"
      }
    }
  }
}
```

**Manual smoke test:**

```bash
docker run -i --rm --network host \
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \
  -e OPENFDD_MCP_TOKEN="$OPENFDD_MCP_TOKEN" \
  ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG}
```

The compose service `openfdd-mcp` (`profiles: ["mcp-sidecar"]`) exists to **pull** the image with the same env/volume wiring as production; interactive MCP clients should use `docker run -i` (or the release binary below), not a detached `up -d`.

## Transport

Stdio JSON-RPC (MCP 2024-11-05). Suitable for Cursor **WSL agent** local config:

```json
{
  "mcpServers": {
    "openfdd": {
      "command": "/path/to/openfdd-mcp",
      "env": {
        "OPENFDD_API_BASE": "http://127.0.0.1:8080",
        "OPENFDD_MCP_TOKEN": "<integrator JWT>",
        "OPENFDD_COMMISSION_BASE": "http://127.0.0.1:9091"
      }
    }
  }
}
```

Docker (stdio):

```bash
docker run -i --rm --network host \
  -e OPENFDD_API_BASE=http://127.0.0.1:8080 \
  -e OPENFDD_MCP_TOKEN="$TOKEN" \
  ghcr.io/bbartling/openfdd-mcp:latest
```

## Tools (phase 1)

| Tool | Description |
|------|-------------|
| `openfdd_bench_topology` | Bench layout from `OPENFDD_BENCH_TOPOLOGY_FILE` or doc pointer |
| `openfdd_driver_status` | Haystack / Modbus / BACnet / JSON API status bundle |
| `openfdd_health` | Bridge liveness |
| `openfdd_haystack_status` | Haystack gateway config (redacted) |
| `openfdd_haystack_test` | Connection test |
| `openfdd_haystack_read` | Filter or ids read |
| `openfdd_bacnet_read` | Commission BACnet point read |

Full contract: [docs/agent/openfdd-mcp-tool-contract.md](../docs/agent/openfdd-mcp-tool-contract.md)

Bench agent prompt: [docs/agent/bench-driver-setup-wsl-agent.md](../docs/agent/bench-driver-setup-wsl-agent.md)

## Build

```bash
cargo build --release -p openfdd-mcp
docker build -f Dockerfile.mcp -t openfdd-mcp:local .
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENFDD_API_BASE` | `http://127.0.0.1:8080` | Bridge REST |
| `OPENFDD_COMMISSION_BASE` | `http://127.0.0.1:9091` | BACnet OT reads |
| `OPENFDD_MCP_TOKEN` | — | Bearer JWT (integrator/agent) |
| `OPENFDD_BENCH_TOPOLOGY_FILE` | — | Gitignored JSON with bench IPs |

Obtain token: `scripts/openfdd_auth_lib.sh` → `openfdd_auth_login_token`.
