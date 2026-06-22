# AI agent guide (Rust edge)

How AI agents (OpenClaw, Cursor, MCP clients) assist with Open-FDD on the **3.2 Rust edge**.

## What AI can do on this stack

| Area | Agent actions | API / UI |
| --- | --- | --- |
| **Deploy** | Bootstrap GHCR stack, validate health, safe updates | `openfdd_rust_edge_bootstrap.sh`, `/api/health` |
| **Drivers** | Inspect driver tree, poll BACnet/Modbus, scan overrides | `/api/bacnet/driver/tree`, `/api/modbus/points` |
| **Haystack model** | Read model, propose point assignments, save bindings | `/api/model/haystack`, `/api/model/assignments` |
| **FDD Wires** | Propose AI assignments (draft), validate graph, approve | `/api/fdd-wires/propose-assignments`, FDD Wires tab |
| **SQL rules** | Build/test/validate DataFusion SQL fault rules | `/api/fdd-rules/builder-sql`, `/api/fdd-rules/{id}/test-sql` |
| **Operations** | Stack check-in, override exports, historian queries | `/api/health/stack`, `/api/bacnet/overrides/export` |
| **Safety** | Read-only by default; integrator required for activation | RBAC on `/api/fdd-rules/{id}/activate` |

## Session start (copy-paste)

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' ~/open-fdd/workspace/auth.env.local | cut -d= -f2- | tr -d '\r')"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg p "$INTEGRATOR_PW" '{username:"integrator",password:$p}')" \
  | jq -r '.token // .access_token')"
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'
```

## Deep guides

- [Haystack modeling and assignments](haystack-and-assignments.md)
- [SQL HVAC FDD rule cookbook](../rule-cookbook/sql-hvac-fdd.md)
- [Assignment model](../ASSIGNMENT_MODEL.md)
- [Agent API reference](../AI_AGENT_API.md)
- [Verification checklists](../verification/README.md)

## Never

- delete `workspace/`
- `docker compose down -v` or `docker volume prune`
- print passwords, tokens, or full `auth.env.local`
- BACnet/Modbus **writes** without explicit human approval
- expose bridge/MCP to the public internet

## GHCR publish (maintainers)

```bash
cargo fmt --all --check && cargo test --workspace
docker build -t openfdd-edge-rust:local .
# Push via .github/workflows/rust-ghcr.yml on master or tag v3.2.0
```
