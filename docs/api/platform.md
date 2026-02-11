---
title: REST API
parent: API Reference
nav_order: 1
---

# REST API

Open-FDD exposes a FastAPI REST API at port 8000. Interactive docs: `/docs`.

---

## Base URL

```
http://localhost:8000
```

---

## Health

### GET /health

Health check.

**Response:** `{"status": "ok"}`

---

## Sites

| Method | Path | Description |
|--------|------|-------------|
| GET | /sites | List all sites |
| POST | /sites | Create site |
| GET | /sites/{id} | Get site |
| PATCH | /sites/{id} | Update site |
| DELETE | /sites/{id} | Delete site |

**Create body:** `{"name": "...", "description": null, "metadata_": {}}`

---

## Equipment

| Method | Path | Description |
|--------|------|-------------|
| GET | /equipment | List equipment (filter by site_id) |
| POST | /equipment | Create equipment |
| GET | /equipment/{id} | Get equipment |
| PATCH | /equipment/{id} | Update equipment |
| DELETE | /equipment/{id} | Delete equipment |

**Create body:** `{"site_id": "uuid", "name": "...", "equipment_type": null, "external_id": null}`

---

## Points

| Method | Path | Description |
|--------|------|-------------|
| GET | /points | List points (filter by site_id, equipment_id) |
| POST | /points | Create point |
| GET | /points/{id} | Get point |
| PATCH | /points/{id} | Update point |
| DELETE | /points/{id} | Delete point |

**Create body:** `{"site_id": "uuid", "equipment_id": null, "external_id": "...", "rule_input": null, "brick_type": null, "name": null, "unit": null}`

---

## Data Model

### GET /data-model/export

Export points as JSON (point_id, site_id, external_id, brick_type, rule_input, etc.). Optional `site_id` filter (UUID or name).

**Response:** `[{ "point_id": "...", "site_id": "...", "external_id": "...", "brick_type": null, "rule_input": null, ... }]`

---

### POST /data-model/import

Import full JSON payload. Creates/updates points. TTL auto-syncs to `config/brick_model.ttl`.

**Body:** Same shape as export; include `point_id` for updates.

---

### GET /data-model/ttl

Generate Brick TTL from current DB state. Returns text/turtle.

---

### POST /data-model/sparql

Run SPARQL query against generated TTL.

**Body:** `{"query": "SELECT ?s ?p ?o WHERE { ... } LIMIT 10"}`

---

### POST /data-model/sparql/upload

Run SPARQL with uploaded TTL file (multipart). Use when validating external TTL.

---

## OpenAPI

- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
