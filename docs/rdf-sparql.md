---
title: RDF and SPARQL
nav_order: 9
---

# RDF export and SPARQL

## Turtle export

The **Model and RDF** tab turns NF's Haystack model into RDF/Turtle (`modelToTurtle()` in `nf-app/static/model.js`):
sites, equipment, devices and points with their markers, refs and labels. Every non-standard tag is defined as a
`ph:marker`, so graphs have no undefined local terms. The tab's checks flag dangling `*Ref` links and
non-standard tags.

### Subjects (unique across sites)

A Haystack id is only unique inside a site: two sites can both have an `AHU-1`. So every subject is the NF record
uuid (`local:<uuid>`) for sites, equipment, devices and points alike. A record without a uuid falls back to a
site-prefixed id (`local:<siteRef>_<id>`; a site is just `local:<id>`). `phIoT:siteRef`, `phIoT:equipRef` and
`phIct:deviceRef` point at those same subjects, resolved through the model inside the referring record's own site; a
ref whose target is not in the model keeps `local:<id>` and shows up as a dangling ref in the checker. The
`rdfs:label` is the display name, so `?e rdfs:label "AHU-1"` can match one equip per site: join through
`phIoT:siteRef` when you mean one of them.

### Time-series references

Each point carries exactly one external reference in Brick's `ref:` schema that says where its history lives:

```turtle
local:u1 a phIoT:point ;
    ref:hasExternalReference [ a ref:TimeseriesReference ;
        ref:hasTimeseriesId "<NF point uuid>" ;
        ref:storedAt local:store_nf ] .
local:store_nf a ref:Database ; rdfs:label "Normal Framework point history" .
```

`ref:hasTimeseriesId` is the NF point uuid; read the data with `GET /api/v1/point/data?uuids=<id>`.

### Checking the Turtle

`tools/rdf-check` runs the same export code in Node on a fixture and validates it with Oxigraph (strict parse) and
rdflib (parse and N-Triples round trip). It also checks that every `*Ref` target exists and every point has one
time-series reference:

```bash
pip install rdflib pyoxigraph
node tools/rdf-check/gen_ttl.js tools/rdf-check/fixtures/model.json out.ttl
python tools/rdf-check/check_ttl.py out.ttl
```

## SPARQL panel (browser)

The Model and RDF tab has a SPARQL panel. Oxigraph (WASM, vendored) is loaded the first time you use it and the
store is rebuilt whenever the model reloads. Example queries are built in (points with time-series ids, equipment
and point kinds, fault result points). Results are capped at 5000 rows and can be downloaded as CSV.

## SPARQL hook (API)

The on-request `sparql` hook runs the same query server-side against the model NF holds right now:

```bash
curl -u "$USER:$PASS" -X POST \
  "$NF/api/v1/apps/open-fdd/hooks/sparql" \
  -H 'Content-Type: application/json' \
  -d '{"args": {"query": "SELECT ?s WHERE { ?s a <http://data.ashrae.org/haystack/phIoT#point> } LIMIT 5", "format": "json"}}'

# the answer:
curl -u "$USER:$PASS" "$NF/api/v1/apps/open-fdd/hooks/sparql/runs?include_results=true"
```

| `args.format` | Result |
|---|---|
| `json` (default) | SELECT: `{kind, vars, rows, total, truncated}`; ASK: `{kind, value}`; CONSTRUCT/DESCRIBE: `{kind, turtle, ...}` |
| `csv` | SELECT/ASK as CSV; graph results as `subject,predicate,object` |
| `turtle` | CONSTRUCT/DESCRIBE only |

The answer is the hook's return value and also one capped log line of the run. Queries are limited to 20,000
characters and the answer to about 200,000. Copy the `PREFIX` lines from the Turtle of the Model and RDF tab. Nothing
in the hook knows a site: the model comes from NF.
