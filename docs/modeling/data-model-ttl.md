---
title: Data model TTL export
parent: Modeling
nav_order: 12
---

# Data model TTL export (Wave S)

Open-FDD can export the **package Mapping inventory** as RDF Turtle. This is a
**derived view** — not the FDD source of truth.

## Contract

| Layer | Role |
| --- | --- |
| Package zip maps → `columns.csv` roles | **SoT** for DataFusion FDD / analytics |
| Mapping JSON export | Same inventory as JSON |
| Mapping **Export TTL** / **View TTL as text** | Same inventory as compact Turtle (`text/turtle`) |
| `GET /api/csv/import/package/mapping/ttl?building_id=…` | JWT + building ACL; agents/MCP can fetch without SPA |

Turtle subjects use safe IRI segments; opaque names become reversible
`enc_<utf8-hex>` (SPA and central must stay UTF-8 parity — not FNV/UTF-16).

## Non-goals

- No SPARQL / Oxigraph on the FDD request path.
- Do not invent Brick/Haystack roles in RDF that the zip does not map.
- Do not treat downloaded `.ttl` as an ingest or authoring format.
- Do not claim lossless JSON↔TTL (legacy Haystack projection declares
  `ofdd:claimsLosslessJson false` — see [RDF vocabulary notes](rdf-vocabulary.html)).

See also: [`docs/agent/PACKAGE_AUTHORING.md`](../agent/PACKAGE_AUTHORING.md),
[Engineering quantities](engineering-quantities.html),
Mapping page (`map-download-ttl`, `map-view-ttl-text`).
