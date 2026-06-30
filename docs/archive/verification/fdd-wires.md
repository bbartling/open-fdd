# FDD Wires and SQL rules verification

Validates the **FDD Wires** graph workspace, DataFusion SQL rule builder, AI assignment proposals, and activation RBAC.

## Prerequisites

```bash
docker compose up -d --build
curl -fsS http://127.0.0.1:8080/api/health
```

Sign in with credentials from `workspace/auth.env.local` (integrator for writes, agent for read-only proposals).

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' workspace/auth.env.local | cut -d= -f2- | tr -d '\r')"
TOKEN="$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg p "$INTEGRATOR_PW" '{username:"integrator",password:$p}')" \
  | jq -r '.token // .access_token')"
```

## FDD Wires graph API

List graphs and load the seeded demo graph (replace `GRAPH_ID` with your site graph):

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8080/api/fdd-wires/graphs?site_id=site:demo' | jq .

curl -fsS -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8080/api/fdd-wires/graphs/GRAPH_ID?site_id=site:demo' \
  | jq '.graph.review_status, (.graph.nodes | length)'
```

## UI smoke

1. Open `http://127.0.0.1:8080` and sign in.
2. **FDD Wires** tab loads the rule graph canvas.
3. Right-click canvas → Validate graph / Propose assignments.
4. Right-click a node → settings / copy JSON.
5. **SQL Rules** tab: toggle Builder / Raw DataFusion SQL; Ctrl/Cmd+Enter runs a query.
6. Product UI must not mention third-party BMS or analytics brands.

## SQL rule builder

```bash
curl -fsS -X POST http://127.0.0.1:8080/api/fdd-rules/builder-sql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"input":"oa_t","operator":">","value":110,"equipment_id":"AHU-1"}' \
  | jq '.sql, .validation.safe'

curl -fsS -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT timestamp, equipment_id, oa_t FROM telemetry_pivot LIMIT 5","confirmation_seconds":300}' \
  | jq '.ok, .engine'

curl -fsS -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/validate-sql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"sql":"DROP TABLE telemetry"}' | jq '.safe, .errors'
```

## AI assignment proposals (draft only)

```bash
AGENT_PW="$(grep '^OFDD_AGENT_PASSWORD=' workspace/auth.env.local | cut -d= -f2- | tr -d '\r')"
AGENT="$(curl -fsS -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg p "$AGENT_PW" '{username:"agent",password:$p}')" \
  | jq -r '.token // .access_token')"

curl -fsS -X POST http://127.0.0.1:8080/api/fdd-wires/propose-assignments \
  -H "Authorization: Bearer $AGENT" -H 'Content-Type: application/json' \
  -d '{"site_id":"site:demo","equipment_type":"ahu"}' \
  | jq '.review_status, .proposals[0].review_status'
```

Expected: `review_status` is `needs_review`; proposals are `ai_suggested`; integrator approval required before activation.

## Activation RBAC

Agent must not activate rules:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/activate \
  -H "Authorization: Bearer $AGENT" -H 'Content-Type: application/json' -d '{}' | jq '.ok, .error'
```

Integrator activates only after graph approval:

```bash
curl -fsS -X POST "http://127.0.0.1:8080/api/fdd-wires/graphs/GRAPH_ID/approve?site_id=site:demo" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}' | jq '.ok'

curl -fsS -X POST "http://127.0.0.1:8080/api/fdd-wires/graphs/GRAPH_ID/activate?site_id=site:demo" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}' | jq '.ok, .activated'
```

## Pass criteria

- Graph schema version present; node chain includes driver → model → FDD input → SQL rule → confirmation → fault output.
- DataFusion executes in Rust; DDL/DML rejected.
- Agent proposals stay draft; integrator-only activation.
- Import/export JSON works from the UI.
