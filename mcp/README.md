# openfdd-mcp

Read-first [Model Context Protocol](https://modelcontextprotocol.io/) server for Open-FDD Rust edge. Proxies JWT-authenticated REST calls to `openfdd-bridge` and commission BACnet reads.

**Image:** `ghcr.io/bbartling/openfdd-mcp`

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
