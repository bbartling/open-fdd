# Haystack model and SPARQL

Open-FDD stores the site model as a **Project Haystack grid** (`workspace/data/model/haystack_grid.json`). The edge projects that grid to **RDF (Turtle)** and serves **read-only SPARQL SELECT** queries via Oxigraph.

## Data flow

```text
Haystack grid JSON
  → RDF projection (hs: + ofdd: prefixes)
  → in-memory Oxigraph store (reloaded on grid save)
  → SPARQL SELECT → JSON bindings
```

Assignments (`/api/model/assignments`) layer driver refs and FDD inputs on top of Haystack point IDs. See [ASSIGNMENT_MODEL.md](../ASSIGNMENT_MODEL.md).

## HTTP API

| Route | Purpose |
|-------|---------|
| `GET /api/model/haystack` | Raw grid (edit/import) |
| `GET /api/model/ttl` | Turtle export |
| `POST /api/model/sync-ttl` | Write `data_model.ttl` to disk |
| `GET /api/model/sparql/predefined` | Named queries for dashboard |
| `POST /api/model/sparql` | Custom SELECT (updates rejected) |
| `GET /api/model/tree` | Site equipment + points |
| `GET /api/model/graph` | Feeds graph for explorer |
| `GET /api/dashboard/model-coverage` | Mapped vs unmapped counts |

Dashboard list/coverage/graph endpoints use the same SPARQL layer internally (`query_engine: "sparql"` in responses).

## SPARQL vocabulary

```sparql
PREFIX hs: <https://project-haystack.org/def/>
PREFIX ofdd: <https://open-fdd.dev/model#>
```

- `?s a hs:Site` / `hs:Equip` / `hs:Point` — entity types
- `?s ofdd:haystackId ?id` — Haystack ref (`site:demo`, `point:oa-t`)
- `?s hs:dis ?label` — display name
- `?s hs:equipRef ?eq` — point → equipment (object IRI; join `ofdd:haystackId` for string id)
- `?s ofdd:equipType ?type` — inferred HVAC type (`ahu`, `vav`, …)

## Example

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/model/sparql/predefined | jq '.queries[0].id'

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/dashboard/model-coverage | jq .
```

UI: **Data model** tab → SPARQL panel runs predefined and custom queries against this graph.
