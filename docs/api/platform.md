---
title: Platform REST API
parent: API Reference
nav_order: 1
---

# Platform REST API

REST API for the Open-FDD platform: CRUD, data model, bulk download, analytics, and FDD trigger. Served by the API container on port 8000.

**Base URL:** `http://localhost:8000`  
**Interactive docs:** When the API is running, open [Swagger UI](http://localhost:8000/docs) or [ReDoc](http://localhost:8000/redoc).

---

## Health

### GET /health

Liveness check. Use for load balancers and monitoring.

| Response | Body |
|----------|------|
| 200 OK   | `{"status": "ok"}` |

---

## Sites

CRUD for sites (buildings or zones). Deleting a site cascades to equipment, points, timeseries, fault results, and fault events. Brick TTL is regenerated after each mutation.

| Method | Path | Description |
|--------|------|-------------|
| GET    | /sites         | List all sites |
| POST   | /sites         | Create site |
| GET    | /sites/{id}    | Get site by UUID |
| PATCH  | /sites/{id}    | Update site |
| DELETE | /sites/{id}    | Delete site and all dependent data |

**Create body (POST /sites):**

| Field         | Type   | Required | Description |
|---------------|--------|----------|-------------|
| name          | string | yes      | Site name |
| description   | string | no       | Optional description |
| metadata_     | object | no       | Optional JSON metadata |

**Update body (PATCH /sites/{id}):** Same fields; omit to leave unchanged.

---

## Equipment

CRUD for equipment (AHUs, VAVs, chillers, etc.) under a site. Deleting equipment cascades to its points and their timeseries. Brick TTL is regenerated after each mutation.

| Method | Path | Description |
|--------|------|-------------|
| GET    | /equipment          | List equipment (optional `?site_id=uuid`) |
| POST   | /equipment          | Create equipment |
| GET    | /equipment/{id}     | Get equipment by UUID |
| PATCH  | /equipment/{id}     | Update equipment |
| DELETE | /equipment/{id}     | Delete equipment and its points |

**Create body (POST /equipment):**

| Field           | Type   | Required | Description |
|-----------------|--------|----------|-------------|
| site_id         | UUID   | yes      | Parent site |
| name            | string | yes      | Equipment name |
| description     | string | no       | Optional |
| equipment_type  | string | no       | e.g. AHU, VAV, Chiller |
| metadata_       | object | no       | Optional JSON (alias: `metadata`) |

**Update body (PATCH /equipment/{id}):** Same fields; omit to leave unchanged.

---

## Points

CRUD for points (sensors, setpoints, commands) that reference timeseries. Deleting a point cascades to its timeseries_readings. Brick TTL is regenerated after each mutation.

| Method | Path | Description |
|--------|------|-------------|
| GET    | /points           | List points (optional `?site_id=uuid` or `?equipment_id=uuid`) |
| POST   | /points           | Create point |
| GET    | /points/{id}      | Get point by UUID |
| PATCH  | /points/{id}      | Update point |
| DELETE | /points/{id}      | Delete point and its timeseries |

**Create body (POST /points):**

| Field              | Type   | Required | Description |
|--------------------|--------|----------|-------------|
| site_id            | UUID   | yes      | Parent site |
| external_id        | string | yes      | BACnet/OT identifier (e.g. object name) |
| equipment_id       | UUID   | no       | Parent equipment |
| brick_type         | string | no       | Brick class (e.g. Supply_Air_Temperature_Sensor) |
| fdd_input          | string | no       | Name FDD rules use for this point (defaults to external_id) |
| unit               | string | no       | Unit of measure |
| description        | string | no       | Optional |
| bacnet_device_id   | string | no       | BACnet device instance (e.g. 3456789). With object_identifier, enables data-model scrape for this point. |
| object_identifier  | string | no       | BACnet object ID (e.g. analog-input,1). |
| object_name        | string | no       | BACnet object name (often same as external_id). |

**Update body (PATCH /points/{id}):** Same fields; omit to leave unchanged. Responses (GET/POST/PATCH) include `bacnet_device_id`, `object_identifier`, `object_name` when set.

---

## BACnet proxy and import

The API proxies to diy-bacnet-server for discovery and can import results into the data model.

| Method | Path | Description |
|--------|------|-------------|
| POST   | /bacnet/server_hello   | Test connection to diy-bacnet-server |
| POST   | /bacnet/whois_range   | Who-Is over an instance range (body: optional `url`, `request`: `{start_instance, end_instance}`) |
| POST   | /bacnet/point_discovery | Point discovery for a device (body: optional `url`, `instance`: `{device_instance}`) |
| POST   | /bacnet/point_discovery_to_graph | **Point discovery → in-memory graph**. Calls the gateway for point discovery (device instance), builds BACnet TTL from JSON, updates the graph and optionally writes `config/brick_model.ttl`. Body: `instance` (device_instance), optional `update_graph`, `write_file`, `url`. |

Config UI at `/app/` provides a BACnet panel. Use **POST /bacnet/point_discovery_to_graph** to put BACnet devices/points into the graph; create points in the DB via CRUD or data-model export/import.

---

## Data model

Brick-semantic data model: export points, bulk import (brick_type, rule_input), generate TTL, run SPARQL. TTL is also auto-synced on every CRUD and import.

### GET /data-model/export

Export points as JSON for editing and re-import. Optional site filter.

| Query param | Type   | Required | Description |
|-------------|--------|----------|-------------|
| site_id     | string | no       | Site UUID or name; omit for all sites |

**Response:** `200 OK` — JSON array of point objects (`point_id`, `site_id`, `external_id`, `brick_type`, `fdd_input`, `unit`, `equipment_id`, etc.).

---

### PUT /data-model/import

Bulk create/update points (and optionally sites/equipment). Used for Brick workflow: export → add brick_type/rule_input → import. TTL is regenerated after import.

**Body:** `{"points": [{ "point_id": "uuid", "brick_type": "...", "rule_input": "sat", ... }, ...]}`

| Field (per point) | Type   | Description |
|-------------------|--------|-------------|
| point_id          | UUID   | Required for updates |
| brick_type        | string | Brick class |
| rule_input        | string | Name FDD rules use (maps to fdd_input in DB) |
| site_id, equipment_id, external_id, unit, description | optional | |

**Response:** `200 OK` — `{"updated": N, "errors": []}`

---

### GET /data-model/ttl

Generate Brick TTL from current DB state. Returns Turtle (text/turtle).

| Query param | Type   | Default | Description |
|-------------|--------|---------|-------------|
| site_id     | string | —       | Filter by site UUID or name; omit for all sites |
| save        | bool   | true    | If true, write TTL to config/brick_model.ttl (best-effort; may fail if read-only) |

**Response:** `200 OK` — Turtle document. On save failure, body still returns TTL; headers `X-TTL-Save: failed` and `X-TTL-Save-Error` indicate the error.

---

### POST /data-model/sparql

Run a SPARQL query against the current data model (TTL generated from DB). Use in Swagger for ad-hoc validation.

**Body:** `{"query": "PREFIX brick: <...> SELECT ?s ?p ?o WHERE { ... } LIMIT 10"}`

**Response:** `200 OK` — `{"bindings": [{ "s": "...", "p": "...", "o": "..." }, ...]}`

**Errors:** `400` invalid TTL or SPARQL; `503` if rdflib not installed (`pip install open-fdd[brick]`).

---

### POST /data-model/sparql/upload

Run a SPARQL query from an uploaded `.sparql` file (e.g. from `analyst/sparql/`). Same behavior as POST /data-model/sparql with the file contents as query.

**Body:** multipart/form-data, file = `.sparql` file.

**Response:** Same as POST /data-model/sparql.

---

## Bulk download

CSV exports are Excel-friendly (UTF-8 BOM, ISO timestamps). Wide format = timestamp column on the left, one column per point.

### GET /download/csv

Download timeseries as CSV. Use for bookmarking or simple curl.

| Query param | Type   | Required | Description |
|-------------|--------|----------|-------------|
| site_id     | string | yes      | Site name or UUID |
| start_date  | date   | yes      | Start of range (YYYY-MM-DD) |
| end_date    | date   | yes      | End of range |
| format      | string | no       | `wide` (default, Excel) or `long` (ts, point_key, value) |

**Response:** `200 OK` — CSV attachment `openfdd_timeseries_{start}_{end}.csv`. `404` if site not found or no data.

---

### POST /download/csv

Same as GET but supports optional point filter in body.

**Body:**

| Field      | Type     | Required | Description |
|------------|----------|----------|-------------|
| site_id    | string   | yes      | Site name or UUID |
| start_date | date     | yes      | Start of range |
| end_date   | date     | yes      | End of range |
| format     | string   | no       | `wide` or `long` (default wide) |
| point_ids  | string[] | no       | Limit to these point UUIDs |

**Response:** Same as GET /download/csv.

---

### GET /download/faults

Export fault results for MSI/cloud integration. Poll this endpoint (e.g. cron) to sync faults into your platform.

| Query param | Type   | Required | Description |
|-------------|--------|----------|-------------|
| start_date  | date   | yes      | Start of range |
| end_date    | date   | yes      | End of range |
| site_id     | string | no       | Site name or UUID; omit for all sites |
| format      | string | no       | `csv` (default, Excel-friendly) or `json` |

**Response:**

- **CSV:** `200 OK` — attachment `openfdd_faults_{start}_{end}.csv` (ts, site_id, equipment_id, fault_id, flag_value, evidence).
- **JSON:** `200 OK` — `{"faults": [...], "count": N}`.

`404` if site_id provided and not found.

---

## Analytics

Data-model driven: results depend on points having the right brick_type (e.g. fan/VFD for motor runtime).

### GET /analytics/motor-runtime

Motor runtime hours from fan/VFD points. If no suitable point exists, returns `NO DATA`.

| Query param | Type   | Required | Description |
|-------------|--------|----------|-------------|
| site_id     | string | yes      | Site name or UUID |
| start_date  | date   | yes      | Start of range |
| end_date    | date   | yes      | End of range |

**Response:** `200 OK` — `{"motor_runtime_hours": 123.45, "point": {...}}` or `{"status": "NO DATA", "reason": "..."}`. Cached to `analytics_motor_runtime` for Grafana.

---

### GET /analytics/fault-summary

Fault counts by fault_id. For dashboards and cloud integration.

| Query param | Type   | Required | Description |
|-------------|--------|----------|-------------|
| start_date  | date   | yes      | Start of range |
| end_date    | date   | yes      | End of range |
| site_id     | string | no       | Site name or UUID; omit for all sites |

**Response:** `200 OK` — `{"site_id": "...", "period": {"start": "...", "end": "..."}, "by_fault_id": [{"fault_id": "...", "count": N, "flag_sum": M}, ...], "total_faults": N}`.

---

## Run FDD now

### POST /run-fdd

Trigger an immediate FDD rule run and reset the loop timer when the fdd-loop container runs with `--loop`. Touches the trigger file; the loop picks it up within 60 seconds.

**Response:** `200 OK` — `{"status": "triggered", "path": "config/.run_fdd_now"}` (or configured path).

---

## OpenAPI

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs) — try all endpoints; version = installed open-fdd package.
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc).
- **OpenAPI JSON:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).
