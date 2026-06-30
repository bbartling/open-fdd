# Haystack model and SPARQL

Open-FDD stores the site model as a **Project Haystack grid** (`workspace/data/model/haystack_grid.json`). The edge projects that grid to **RDF (Turtle)** compatible with **OxiGraph** and serves **read-only SPARQL SELECT** queries.

## Vocabulary

| Prefix | Namespace | Use |
|--------|-----------|-----|
| `hs:` | `https://project-haystack.org/def/` | Project Haystack tags (`dis`, `siteRef`, `equipRef`, `kind`, `unit`, point roles) |
| `ofdd:` | `https://open-fdd.dev/model#` | Open-FDD application metadata (`haystackId`, `equipType`, `csvRef`, `fddInput`, …) |

Open-FDD-only predicates are **not** emitted under `hs:`:

- `ofdd:csvRef`, `ofdd:fddInput`, `ofdd:importJob`, `ofdd:protocol`

Haystack relationship tags stay under `hs:`:

- `hs:dis`, `hs:siteRef`, `hs:equipRef`, `hs:sourceRef`, `hs:kind`, `hs:unit`

Every `hs:Point` includes **both** `hs:siteRef` and `hs:equipRef`, plus at least one role marker (`hs:sensor`, `hs:cmd`, `hs:sp`, or `hs:synthetic`). CSV telemetry defaults to `hs:sensor true`.

Optional legacy duplicates (`hs:csvRef`, …) are available when `OPENFDD_RDF_LEGACY_HS_CUSTOM_TAGS=1`.

## Data flow

```text
Haystack grid JSON
  → RDF projection (hs: + ofdd: prefixes, compact Turtle)
  → in-memory Oxigraph store (reloaded on grid save)
  → SPARQL SELECT → JSON bindings
```

Assignments (`/api/model/assignments`) layer driver refs and FDD inputs on top of Haystack point IDs. See [ASSIGNMENT_MODEL.md](../ASSIGNMENT_MODEL.md).

Example fixture: `edge/tests/fixtures/rdf/school_kw_merged_expected.ttl`

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

## Example SPARQL

```sparql
PREFIX hs: <https://project-haystack.org/def/>
PREFIX ofdd: <https://open-fdd.dev/model#>

# All points for a site (direct siteRef on each point)
SELECT ?point ?dis ?equipRef WHERE {
  ?p a hs:Point .
  ?p ofdd:haystackId ?point .
  ?p hs:siteRef ?site .
  ?site ofdd:haystackId "site:school-kw-merged" .
  OPTIONAL { ?p hs:dis ?dis . }
  OPTIONAL { ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equipRef . }
}

# Points on one equipment
SELECT ?point ?dis WHERE {
  ?p a hs:Point .
  ?p ofdd:haystackId ?point .
  ?p hs:equipRef ?eq .
  ?eq ofdd:haystackId "equip:school-kw-merged" .
  OPTIONAL { ?p hs:dis ?dis . }
}

# CSV source lineage for a point
SELECT ?csvRef ?source ?importJob WHERE {
  ?p a hs:Point .
  ?p ofdd:haystackId "point:school-kw-merged-temp_f" .
  ?p ofdd:csvRef ?csv .
  ?csv ofdd:haystackId ?csvRef .
  OPTIONAL { ?p hs:sourceRef ?src . ?src ofdd:haystackId ?source . }
  OPTIONAL { ?src ofdd:importJob ?importJob . }
}

# FDD input mapping
SELECT ?fddInput WHERE {
  ?p a hs:Point .
  ?p ofdd:haystackId "point:school-kw-merged-temp_f" .
  ?p ofdd:fddInput ?fddInput .
}
```

## curl

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/model/sparql/predefined | jq '.queries[0].id'

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/model/ttl

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/api/dashboard/model-coverage | jq .
```

UI: **Data model** tab → SPARQL panel runs predefined and custom queries against this graph.
