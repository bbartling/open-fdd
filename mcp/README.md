# openfdd-mcp

Read-first [Model Context Protocol](https://modelcontextprotocol.io/) server for Open-FDD. Proxies JWT-authenticated REST calls to **central** and commission BACnet reads.

Open-FDD does **not** include a built-in AI chatbot. External agents (Codex CLI, Cursor, Claude Desktop, OpenClaw, etc.) connect through this optional stdio server or JWT REST — see [docs/examples/external-agents.md](../docs/examples/external-agents.md).

**Image:** the slim `ghcr.io/bbartling/openfdd-mcp` image is an MCP stdio entrypoint only, published on the same channel tags as the rest of the stack (`OPENFDD_IMAGE_TAG`). See [docs/operations/build-recipes.md](../docs/operations/build-recipes.md).

## Pull and wire after the stack is healthy

MCP is opt-in — bring up a stack recipe first, then pull MCP on the **same tag**.

```bash
cd ~/open-fdd
export OPENFDD_IMAGE_TAG=nightly   # or a pinned semver / sha-*

# Pull the slim MCP image (docker run will also pull if missing)
./scripts/openfdd_stack_pull.sh mcp

# JWT for central REST (integrator or agent role)
source scripts/openfdd_auth_lib.sh
INTEGRATOR_PW="$(openfdd_auth_plaintext_password workspace/auth.env.local integrator)"
export OPENFDD_MCP_TOKEN="$(
  curl -s -X POST http://127.0.0.1:8080/api/auth/login \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token'
)"
```

**Cursor (stdio via Docker)** — MCP speaks JSON-RPC on stdin/stdout, not HTTP. Use `OPENFDD_API_BASE=http://central:8080` inside the compose network, or `http://127.0.0.1:8080` from the host:

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
        "ghcr.io/bbartling/openfdd-mcp:nightly"
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

Interactive MCP clients should use `docker run -i` (or the release binary below), not a detached `up -d`.

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

## Tools

| Tool | Description |
|------|-------------|
| `openfdd_health` | Central liveness |
| `openfdd_driver_status` | Driver status bundle |
| `openfdd_bench_topology` | Bench layout file or doc pointer |
| `openfdd_haystack_status` | Haystack gateway status |
| `openfdd_haystack_test` | Connection test |
| `openfdd_haystack_read` | Haystack read by filter or ids |
| `openfdd_bacnet_read` | Commission BACnet point read |
| `openfdd_model_sparql_catalog` | Predefined SPARQL queries |
| `openfdd_model_sparql` | Execute SPARQL SELECT on Haystack RDF |
| `openfdd_model_sites` | Site list |
| `openfdd_model_coverage` | Mapped vs unmapped points |
| `openfdd_csv_import_preview` | Stage CSVs from host path or base64 |
| `openfdd_csv_import_plan` | Append/join plan + validation preview |
| `openfdd_csv_fusion_preview` | Merged grid preview |
| `openfdd_csv_import_execute` | Save to Arrow (write gate) |
| `openfdd_historian_query` | Historian pivot query |
| `openfdd_fdd_rules_list` | FDD rule catalog |
| `openfdd_fdd_rule_test_sql` | Test rule SQL |
| `openfdd_fdd_run` | Run ad-hoc FDD SQL (write gate) |
| `openfdd_model_assignments_save` | Save assignments (write gate) |
| `openfdd_reports_draft` / `patch` / `render_pdf` | Report → PDF pipeline (write gate) |

Contract: [ingest contract (archive)](../docs/archive/agent/ingest-contract-v1.md) · [MCP docs](https://bbartling.github.io/open-fdd/mcp-agents/mcp.html)

Bench agent prompt (archive): [docs/archive/agent/bench-driver-setup-wsl-agent.md](../docs/archive/agent/bench-driver-setup-wsl-agent.md)

## Build

```bash
cargo build --release -p openfdd-mcp
docker build -f Dockerfile.mcp -t openfdd-mcp:local .
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENFDD_API_BASE` | `http://127.0.0.1:8080` | Central REST (`http://central:8080` in compose) |
| `OPENFDD_COMMISSION_BASE` | `http://127.0.0.1:9091` | BACnet OT reads |
| `OPENFDD_MCP_TOKEN` | — | Bearer JWT (integrator/agent) |
| `OPENFDD_MCP_ALLOW_WRITES` | — | Set to `1` to enable write tools (requires `confirm:true` per call) |
| `OPENFDD_MCP_TIMEOUT_SECS` | `120` | Default REST timeout |
| `OPENFDD_MCP_CSV_TIMEOUT_SECS` | `600` | Large CSV multipart upload timeout |
| `OPENFDD_BENCH_TOPOLOGY_FILE` | — | Gitignored JSON with bench IPs |

Obtain token: `scripts/openfdd_auth_lib.sh` → `openfdd_auth_login_token`.
