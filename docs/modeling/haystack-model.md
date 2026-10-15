---
title: Haystack model
parent: Modeling
nav_order: 1
---

# Haystack model

Semantic model: package **semantic meta / TTL** + Timescale dims. Soft-OPEN ≠ FQ. See [Modeling](./) for DB design.

## Core endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/sites` | Sites |
| GET | `/api/model/equipment` | Equipment |
| GET | `/api/model/points` | Points |
| GET | `/api/model/tree` | Tree |
| GET | `/api/model/graph` | Graph export |
| POST | `/api/model/query` | Model query |
| POST | `/api/model/sparql` | SPARQL (SELECT/ASK) |
| GET | `/api/model/sparql/predefined` | Templates |
| GET | `/api/model/point-resolve` | Opaque point → SQL |

## Import / export

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/commissioning-export` | Export JSON |
| POST | `/api/model/commissioning-import` | Import (fail-closed) |
| POST | `/api/model/haystack/import` | Zinc/JSON |
| GET | `…/mapping/haystack.ttl` | Strict Haystack TTL |

UI: **Model** (`/model`) — Import · Explorer · FDD mapping · SPARQL.
