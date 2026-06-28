# AI agent context

Rust-only edge runtime. Use JWT REST and safe lifecycle scripts — no Python stack required.

## Guides

| Task | Document |
|------|----------|
| Haystack + assignments | [ai-agent/haystack-and-assignments.md](ai-agent/haystack-and-assignments.md) |
| SQL FDD rules | [rule-cookbook/sql-hvac-fdd.md](rule-cookbook/sql-hvac-fdd.md) |
| MCP tools | [agent/openfdd-mcp-tool-contract.md](agent/openfdd-mcp-tool-contract.md) |
| Full index | [ai-agent/README.md](ai-agent/README.md) |

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
GET  /api/model/haystack
GET  /api/model/sparql/predefined
POST /api/model/sparql
GET  /api/model/assignments
GET  /api/bacnet/driver/tree
POST /api/fdd-wires/propose-assignments
POST /api/fdd-rules/{id}/test-sql
```

## Safe scripts

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

## Never

- Delete `workspace/`
- Run `docker compose down -v` or `docker volume prune`
- Print tokens or `auth.env.local`
- BACnet/Modbus/Haystack **writes** without explicit human approval
