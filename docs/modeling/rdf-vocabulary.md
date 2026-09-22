---
title: RDF vocabulary notes
parent: Haystack Modeling
nav_order: 15
permalink: /modeling/rdf-vocabulary.html
---

# RDF vocabulary notes (DM-10 projection honesty)

Two namespaces remain in-tree (ADR freeze):

| Use | Namespace |
| --- | --- |
| Package / SPA mapping TTL | `urn:openfdd:ns#` |
| Legacy commissioning / edge Haystack projection | `https://open-fdd.dev/model#` |

## Haystack projection version

Edge Turtle built from the Haystack grid declares:

- `ofdd:projectionVersion "ofdd_haystack_projection_v1"`
- `ofdd:claimsLosslessJson false`

Role markers (`hs:sensor`, `hs:cmd`, …) are emitted **only** when present on the
grid row. The projection does **not** invent `hs:sensor` for unlabeled points,
does **not** claim Haystack/Brick equivalence, and does **not** claim lossless
JSON↔TTL round-trip.

## Engineering vocabulary

Shared engineering properties live under `urn:openfdd:ns#` — see
[Engineering quantities](engineering-quantities.html). Do not mint Open-FDD
properties inside Project Haystack or Brick namespaces.

## Product SPARQL

Product central may report SPARQL **unavailable**; legacy edge SPARQL is a
separate route. See [consumer route matrix](consumer-route-matrix.html).
