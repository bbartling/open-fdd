---
title: Haystack
parent: Drivers
nav_order: 3
---

# Haystack driver

The **Haystack gateway** container connects to a remote Project Haystack server (including nHaystack-compatible endpoints) and syncs sites/points into the Open-FDD model.

## Key API routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/haystack/about` | Server metadata |
| GET/POST | `/api/haystack/config` | Connection settings |
| POST | `/api/haystack/read` | Haystack read op |
| POST | `/api/haystack/nav` | Navigation |
| POST | `/api/haystack/import` | Import into model |
| GET | `/api/haystack/driver/tree` | Gateway tree |

## Model integration

- `GET /api/model/haystack` — merged Haystack view
- `POST /api/model/haystack/import` — model import
- `POST /api/model/sparql` — SPARQL over RDF store

## Dashboard

**Haystack** tab (`/haystack`) — configure server URL/credentials, browse sites, import points.
