---
title: Haystack model
parent: Haystack Modeling
nav_order: 1
---

# Haystack model

The semantic model lives in the edge RDF store and is exposed via REST and the **Model & FDD assignments** tab (`/model`).

## Core endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/sites` | Sites |
| GET | `/api/model/equipment` | Equipment |
| GET | `/api/model/points` | Points |
| GET | `/api/model/tree` | Hierarchical tree |
| GET | `/api/model/graph` | Graph export |
| POST | `/api/model/query` | Model query |
| POST | `/api/model/sparql` | SPARQL queries |
| GET | `/api/model/sparql/predefined` | Saved queries |

## Import / export

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/commissioning-export` | Export commissioning JSON |
| POST | `/api/model/commissioning-import` | Import (fail-closed validation) |
| POST | `/api/model/haystack/import` | Haystack zinc/JSON import |

## Dashboard sub-tabs

- **Import / export** — commissioning JSON round-trip
- **Explorer** — browse model graph
- **Haystack RDF** — SPARQL panel
- **Advanced** — TTL and raw JSON views

## BACnet sync

`GET/POST /api/model/bacnet-sync` — align BACnet discovery with model entities.
