# AI-assisted Haystack modeling and assignments

Open-FDD binds **drivers → Haystack IDs → FDD inputs → DataFusion SQL rules**. AI agents help draft assignments; humans approve before activation.

## Data flow

```text
BACnet / Modbus / JSON point
    → Haystack point ID (point:sat, point:oa-t)
    → FDD input (sat, oa_t)
    → SQL rule (fault_raw column)
    → confirmation timer → fault output
```

See [ASSIGNMENT_MODEL.md](../ASSIGNMENT_MODEL.md) for the binding contract.

## Read the site model

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/model/haystack | jq .
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/model/assignments | jq .
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | jq '.drivers[0].devices[0].points'
```

## AI propose assignments (draft only)

Agents call **propose** — output stays `needs_review` until an integrator approves in the UI or via API.

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-wires/propose-assignments \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"site_id":"site:demo","equipment_type":"ahu"}' | jq '.review_status, .proposals[0]'
```

Expected:

- `review_status`: `needs_review`
- Each proposal: `ai_suggested`, confidence in `provenance`
- No external LLM required in CI — heuristic proposals seed the workflow

## Save human-reviewed assignments

```bash
curl -s -X POST http://127.0.0.1:8080/api/model/assignments/save \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "points": [{
      "haystack_id": "point:oa-t",
      "driver_bindings": [{"driver":"bacnet","ref":"bacnet:5007:analog-input:1173"}],
      "fdd_input": "oa_t"
    }]
  }' | jq .
```

## FDD Wires graph (visual)

1. Open dashboard → **FDD Wires** tab
2. Right-click canvas → **Propose assignments**
3. Validate graph → approve → activate (integrator only)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8080/api/fdd-wires/graphs?site_id=site:demo' | jq .
```

## Agent prompt snippet

```text
You are modeling a site on Open-FDD Rust edge.

1. Login as integrator (never print password).
2. GET /api/bacnet/driver/tree — list commissioned points.
3. GET /api/model/haystack and /api/model/assignments — current bindings.
4. POST /api/fdd-wires/propose-assignments for equipment_type ahu — draft only.
5. Present proposals to the human; do not activate without approval.
6. Map each driver ref to a Haystack ID before saving SQL rules.
7. Use /api/fdd-rules/builder-sql to preview SQL from FDD inputs.
```

## Bench device 5007 example

Seeded points on the demo bench controller (device instance **5007**):

| BACnet ref | Haystack ID | FDD input |
| --- | --- | --- |
| `bacnet:5007:analog-input:1173` | `point:oa-t` | `oa_t` |
| `bacnet:5007:analog-input:1168` | `point:oa-h` | `oa_h` |
| `bacnet:5007:analog-input:1192` | `point:duct-t` | `duct_t` |
| `bacnet:5007:analog-input:10014` | `point:stat_zn-t` | `zone_t` |

Use these when drafting SQL rules for the bench AHU — see [SQL HVAC FDD cookbook](../rule-cookbook/sql-hvac-fdd.md).
