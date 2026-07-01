# Agent Guide (Rust edge + external agents)

Open-FDD **3.2.x** is a **deterministic Rust edge runtime** (`ghcr.io/bbartling/openfdd-edge-rust`). It does **not** ship an embedded AI chatbot. External orchestrators — Codex CLI, Cursor, OpenClaw, Claude Desktop, or any MCP host — connect via **JWT REST** and optional **`openfdd-mcp` stdio**.

| Layer | Responsibility |
| --- | --- |
| **Rust edge** | Bridge, historian, FDD, reports, dashboard (no LLM runtime) |
| **External agent** | Operator tooling outside Open-FDD — MCP or REST |
| **Optional MCP** | Read-first `openfdd-mcp` — [mcp/README.md](mcp/README.md); not started by site update |

**Docs:** [External agents](docs/examples/external-agents.md) · [MCP README](mcp/README.md) · [API routes](https://bbartling.github.io/open-fdd/api/routes.html)

Use Rust lifecycle scripts and JSON API. No Python runtime required.

## Start session

After auth merge on `master`:

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' ~/open-fdd/workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"
```

Discover routes: `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'`

## Safe scripts

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_check_ghcr_platform.sh
./scripts/openfdd_rust_edge_validate.sh
```

## External agent workflow

1. Edge healthy on LAN/VPN only — never expose on public internet.
2. JWT for integrator or agent role.
3. `openfdd-mcp` stdio outside the web UI, or REST `/api/agent/tools`.
4. Read-first; writes need `OPENFDD_MCP_ALLOW_WRITES=1` and `confirm:true`.
5. Never print secrets. BACnet writes need explicit human approval.

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- print secrets or tokens
- expose API on public internet
- write BACnet without explicit human approval
- embed vendor chat relays or model API keys in the edge stack

## Assignment rule

Bind drivers → Haystack IDs → FDD/CDL via `/api/model/assignments`.

See [docs/ai-agent-context.md](docs/ai-agent-context.md) for API context.
