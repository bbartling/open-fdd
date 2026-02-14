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

## Bulk Download

CSV exports are **Excel-friendly** (UTF-8 BOM, ISO timestamps). Wide format = timestamp column on left, one column per point — opens directly in Excel.

### GET /download/csv

Download timeseries (researcher-friendly). Use for bookmarking or simple curl.

**Query params:** `site_id`, `start_date`, `end_date`, `format` (default `wide`)

### POST /download/csv

Same as GET but supports `point_ids` filter in the body.

**Body:**

```json
{
  "site_id": "default",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "format": "wide",
  "point_ids": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `site_id` | string | Site name or UUID |
| `start_date` | date | Start of range |
| `end_date` | date | End of range |
| `format` | string | `wide` (pivot by point, Excel default) or `long` (ts, point_key, value) |
| `point_ids` | string[] | Optional; limit to these point UUIDs |

**Response:** CSV attachment (`openfdd_timeseries_{start}_{end}.csv`).

---

### GET /download/faults

Export fault results for MSI/cloud integration. Poll this endpoint (e.g. cron, scheduler) to sync faults into your platform.

**Query params:** `start_date`, `end_date`, `site_id` (optional; omit for all sites), `format` (default `csv`)

| Param | Type | Description |
|-------|------|-------------|
| `site_id` | string | Optional. Site name or UUID; omit for all sites |
| `start_date` | date | Start of range |
| `end_date` | date | End of range |
| `format` | string | `csv` (Excel-friendly) or `json` (for REST/ETL) |

**Response:**

- **CSV:** `openfdd_faults_{start}_{end}.csv` (ts, site_id, equipment_id, fault_id, flag_value, evidence)
- **JSON:** `{"faults": [...], "count": N}`

---

## Fault analytics (data-model driven)

### GET /analytics/motor-runtime

Motor runtime hours from fan/VFD points. **Data-model driven:** if no point with brick_type (Supply_Fan_Status, Supply_Fan_Speed_Command, VFD, etc.), returns `NO DATA`.

**Query params:** `site_id`, `start_date`, `end_date`

**Response:** `{"motor_runtime_hours": 123.45, "point": {...}}` or `{"status": "NO DATA", "reason": "..."}`

Caches to `analytics_motor_runtime` for Grafana. Poll this (or run cron) to populate.

### GET /analytics/fault-summary

Fault counts by fault_id. **Query params:** `start_date`, `end_date`, `site_id` (optional).

---

## Trigger FDD run

### POST /run-fdd

Trigger an immediate FDD rule run and reset the loop timer (when fdd-loop runs with `--loop`). Touches the trigger file; the loop picks it up within 60 seconds.

**Response:** `{"status": "triggered", "path": "..."}`

---

## OpenAPI

- Swagger: http://localhost:8000/docs (version shown = installed open-fdd package)
- ReDoc: http://localhost:8000/redoc
