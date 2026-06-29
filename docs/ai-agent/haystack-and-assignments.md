# AI-assisted Haystack modeling

Binding chain: **driver ref → Haystack point ID → FDD input → DataFusion SQL**. Agents draft; integrators approve.

See [ASSIGNMENT_MODEL.md](../ASSIGNMENT_MODEL.md).

## Read model state

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/model/haystack | jq '.rows | length'
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/model/assignments | jq .
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | jq .
```

## SPARQL (preferred for analytics)

Model queries run against the RDF projection — use SPARQL instead of scanning the raw grid.

```bash
# Predefined catalog
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/model/sparql/predefined | jq '.queries[].id'

# Sites
curl -s -X POST http://127.0.0.1:8080/api/model/sparql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"PREFIX hs: <https://project-haystack.org/def/> PREFIX ofdd: <https://open-fdd.dev/model#> SELECT ?point ?dis ?equipRef ?fddInput WHERE { ?p a hs:Point . ?p ofdd:haystackId ?point . OPTIONAL { ?p hs:dis ?dis . } OPTIONAL { ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equipRef . } OPTIONAL { ?p ofdd:fddInput ?fddInput . } }"}'
```

Turtle export: `GET /api/model/ttl` · Coverage: `GET /api/dashboard/model-coverage`

Details: [modeling/haystack_dashboard_model.md](../modeling/haystack_dashboard_model.md)

## Propose assignments (draft)

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-wires/propose-assignments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"site_id":"site:demo","equipment_type":"ahu"}' | jq '.review_status'
```

Expect `needs_review` — do not activate without human approval.

## Save reviewed bindings

```bash
curl -s -X POST http://127.0.0.1:8080/api/model/assignments/save \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"points":[{"haystack_id":"point:oa-t","driver_bindings":[{"driver":"bacnet","ref":"bacnet:5007:analog-input:1173"}],"fdd_input":"oa_t"}]}'
```

## Agent checklist

1. Authenticate (never log password or token).
2. `GET /api/bacnet/driver/tree` — commissioned points.
3. `POST /api/model/sparql` or predefined queries — model structure.
4. `GET /api/model/assignments` — current bindings.
5. `POST /api/fdd-wires/propose-assignments` — draft only.
6. Present proposals to operator before save or rule activation.

Lab benches: use gitignored profiles under `workspace/smoke-profiles/local/` — do not hardcode device IDs in production code.
