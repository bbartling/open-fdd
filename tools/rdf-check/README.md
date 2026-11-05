# RDF check for the app's Haystack Turtle

The Model & RDF tab builds Turtle in the browser with `modelToTurtle()` in `nf-app/static/model.js`.
These scripts run that exact code in Node on a generic fixture (no live NF) and validate the result:

```bash
pip install rdflib pyoxigraph
node tools/rdf-check/gen_ttl.js tools/rdf-check/fixtures/model.json out.ttl
python tools/rdf-check/check_ttl.py out.ttl      # exit 1 on any problem
```

Checks: strict Turtle parse (Oxigraph) + rdflib parse and N-Triples round trip; every `*Ref` target is a
defined entity; no undefined `local:` terms; labels and `siteRef`s present; and (slice 6) every point has
exactly one NF time-series reference (Brick `ref:`) with a non-empty `ref:hasTimeseriesId`.

## Time-series reference scheme

```turtle
local:u1 a phIoT:point ;
    ref:hasExternalReference [ a ref:TimeseriesReference ;
        ref:hasTimeseriesId "<NF point uuid>" ;
        ref:storedAt local:store_nf ;
        rdfs:seeAlso <{origin}/api/v1/point/data?uuids=<uuid>> ] .
local:store_nf a ref:Database ; rdfs:label "Normal Framework point history" .
```

The URL base is the page origin at export time (or `opts.nfBase`). Full profile: pass
`opts.timescale = {label, uri}` to add a second reference per point stored at `local:store_timescaledb`.
