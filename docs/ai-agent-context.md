# AI agent context

Rust-only edge runtime. Use JWT REST and safe lifecycle scripts — no Python stack required.

**Index:** [agent/index.md](agent/index.md) · [examples/external-agents.md](examples/external-agents.md)

## Session login

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' ~/open-fdd/workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"
```

## Key endpoints

```text
GET  /api/health/stack
GET  /api/agent/tools
GET  /api/agent/config
GET  /api/model/haystack
POST /api/fdd-rules/{id}/test-sql
```

## Safe scripts

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
./scripts/openfdd_rust_edge_validate.sh
```

External agents (Codex, Cursor, MCP hosts) run **outside** the dashboard — see [agent/model-routing.md](agent/model-routing.md).
