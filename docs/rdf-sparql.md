---
title: RDF and SPARQL
nav_order: 14
---

# RDF and SPARQL

The Model and RDF tab exports the NF Haystack model as Turtle. Sites, equipment, devices, and points use stable
subjects. References are resolved within their site. Each point includes a reference to its NF time-series id.

The tab checks dangling references and non-standard tags. To validate an exported Turtle file locally, pass that file
directly to the repository checker. Run this command:

```bash
pip install rdflib pyoxigraph
python tools/rdf-check/check_ttl.py model.ttl
```

To generate Turtle from a JSON fixture, include a `records` array in the fixture. Run these commands:

```bash
node tools/rdf-check/gen_ttl.js fixture.json fixture.ttl
python tools/rdf-check/check_ttl.py fixture.ttl
```

## Browser SPARQL

The browser panel queries the loaded model with SELECT, ASK, CONSTRUCT, or DESCRIBE. Results are capped and can be
downloaded as CSV. Update operations and remote SERVICE queries are refused.

## SPARQL hook

Full edition provides an on-request read-only hook. Submit a query through the app's SPARQL hook route using NF
console authentication. Then read the run result from the hook runs route.

```http
POST /api/v1/apps/{app-id}/hooks/sparql
Content-Type: application/json

{"args":{"query":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 5","format":"json"}}
```

The result is available at
`GET /api/v1/apps/{app-id}/hooks/sparql/runs?include_results=true`. Formats are JSON (default), CSV, or Turtle for
graph results. Query length and output size are capped. See [API reference](fdd-data-access.html).
