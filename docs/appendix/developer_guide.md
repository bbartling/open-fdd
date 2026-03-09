---
title: Developer guide
parent: Appendix
nav_order: 2
nav_exclude: true
---

> **TODO:** This document references Home Assistant (HA) integration and stack/ha_integration. HA integration has been removed from the project; content may be outdated.

# Developer guide

This page is for **developers and contributors** who work on the Open-FDD codebase: front-end (Config UI), database schema, and where to find the rest of the technical reference. For day-to-day operations and usage, see [Getting started](../getting_started) and the [Documentation](../) index.

---

## Front-end: Config UI

The **Configuration UI** is the small web app served at **`/app/`** when you open the API (e.g. http://localhost:8000/app/). It lets users browse the data model (sites, equipment, points), check BACnet status, and trigger an FDD run. It is **plain HTML, CSS, and JavaScript** — no Node, no bundler, no build step.

### Where the code lives

| Path | Purpose |
|------|--------|
| `open_fdd/platform/static/` | All Config UI assets |
| `open_fdd/platform/static/index.html` | Single-page layout, nav, panels |
| `open_fdd/platform/static/app.js` | API calls, DOM updates, BACnet status, Run FDD button |
| `open_fdd/platform/static/styles.css` | Layout and theme (e.g. `.ofdd-sidebar`, `.bacnet-badge`) |

The API serves this directory with FastAPI’s `StaticFiles` mounted at `/app` (see `open_fdd/platform/api/main.py`). So `/app/` and `/app/index.html` resolve to `static/index.html`; `/app/styles.css` and `/app/app.js` to the same filenames in `static/`.

### How to develop the front-end

1. **Run the API locally** (with a real or mock backend):
   - From repo root: `pip install -e ".[platform,brick]"` then start the API (e.g. `uvicorn open_fdd.platform.api.main:app --reload --host 0.0.0.0 --port 8000`), or
   - Use the full stack: `./scripts/bootstrap.sh` so the API runs in Docker.
2. **Edit files** in `open_fdd/platform/static/` (HTML, JS, or CSS).
3. **Reload the browser** at http://localhost:8000/app/ — there is no build step; changes are picked up on refresh. If you run the API in Docker, ensure the repo is mounted so your edits are visible inside the container (bootstrap mounts the repo into the API container where applicable).
4. **API surface:** The UI calls the same REST API as the rest of the platform (e.g. GET `/config`, GET `/sites`, GET `/equipment`, GET `/points`, POST `/run-fdd/trigger`, GET `/health`). It does not use a separate “front-end API”; it uses the OpenAPI-documented endpoints. Auth: if `OFDD_API_KEY` is set, the Config UI is still served without auth (see `auth.py`), but your JS can send `Authorization: Bearer <key>` if you add authenticated calls later.

### Where WebSockets come from (and how bootstrap fits)

**WebSockets are provided by the same Open-FDD API** that serves the Config UI and REST. There is no separate WebSocket server.

- **Endpoint:** `GET /ws/events` (HTTP upgrade to WebSocket). Implemented in `open_fdd/platform/realtime/ws.py`; the hub in `realtime/hub.py` manages connections and broadcasts events (e.g. `fault.*`, `fdd.run.*`, `crud.point.*`).
- **Auth:** When `OFDD_API_KEY` is set, pass it as the query param `token` (e.g. `ws://localhost:8000/ws/events?token=YOUR_KEY`). Unauthorized connections are closed with 4401.
- **Bootstrap:** `./scripts/bootstrap.sh` starts the full stack, including the **API container** (`openfdd_api`). That single process serves REST, the Config UI at `/app`, and the WebSocket at `/ws/events`. So after bootstrap, the WebSocket is already available at the same host and port as the API (e.g. `ws://localhost:8000/ws/events`). No extra step or container is required.
- **Config UI:** The current Config UI uses only REST (no WebSocket in the static JS). The WebSocket is used by the **Home Assistant integration** and **Node-RED** for live updates; front-end devs can add a WebSocket client in `app.js` if they want real-time updates in the browser.

### Stack and conventions

- **Bootstrap 5** is loaded from CDN in `index.html` (`bootstrap.min.css`). No npm or package.json.
- **No framework** — vanilla JS in `app.js` (fetch, DOM, event listeners).
- **Styling** — `styles.css` uses CSS variables and Bootstrap overrides where needed (e.g. `.text-ofdd-primary`, `.ofdd-sidebar`).

Adding a new page or panel means editing `index.html` and `app.js` (and optionally `styles.css`). For a larger SPA or build pipeline, you could later introduce a proper front-end stack and point the API’s `/app` mount at a build output directory; the current design keeps the bar low for small tweaks.

---

## Database schema (TimescaleDB)

The **single source of truth** for the schema is the migration files in **`stack/sql/`**. Migrations are applied in order by bootstrap (and on container start). They are **idempotent** (`CREATE TABLE IF NOT EXISTS`, etc.), so re-running is safe.

### Migration files (order matters)

| Migration | Contents |
|-----------|----------|
| `001_init.sql` | TimescaleDB extension |
| `002_crud_schema.sql` | sites, ingest_jobs, points, timeseries_readings (hypertable), fault_results (hypertable), fault_events |
| `003_equipment.sql` | equipment (site_id, feeds_equipment_id, fed_by_equipment_id) |
| `004_fdd_input.sql` | FDD rule input columns on points |
| `005_bacnet_points.sql` | BACnet-related columns on points (bacnet_device_id, object_identifier, object_name) |
| `006_host_metrics.sql` | host_metrics, container_metrics, disk_metrics (hypertables) |
| `007_retention.sql` | Retention policy (drop chunks older than OFDD_RETENTION_DAYS) |
| `008_fdd_run_log.sql` | fdd_run_log (last run for UI) |
| `009_analytics_motor_runtime.sql` | analytics_motor_runtime |
| `010_equipment_feeds.sql` | Equipment feeds/fed_by (if not already in 003) |
| `011_polling.sql` | polling flag on points |
| `012_fault_definitions.sql` | fault_definitions (fault_id, name, severity, expression, etc.) |
| `013_seed_fault_definitions.sql` | Seed rows for fault_definitions |
| `014_drop_legacy_weather_tables.sql` | Drop legacy weather tables (weather data in timeseries_readings) |
| `015_fault_state_and_audit.sql` | fault_state (current active fault per site/equipment/fault_id for HA), bacnet_write_audit |

### Tables and purpose (quick reference)

| Table | Purpose |
|-------|---------|
| **sites** | Buildings/facilities (id, name, description, metadata, created_at). |
| **equipment** | Devices per site (id, site_id, name, equipment_type, feeds_equipment_id, fed_by_equipment_id). |
| **points** | Brick-style points; link to timeseries (site_id, equipment_id, external_id, brick_type, fdd_input, bacnet_*, polling, etc.). |
| **timeseries_readings** | Hypertable: ts, site_id, point_id, value, job_id (BACnet + weather + CSV ingest). |
| **ingest_jobs** | CSV ingest metadata (site_id, format, point_columns, row_count). |
| **fault_results** | Hypertable: ts, site_id, equipment_id, fault_id, flag_value, evidence. |
| **fault_events** | Fault start/end (id, site_id, equipment_id, fault_id, start_ts, end_ts, duration_seconds, evidence). |
| **fault_state** | Current active fault per (site_id, equipment_id, fault_id) for HA binary_sensors. |
| **fault_definitions** | fault_id, name, description, severity, category, equipment_types, inputs, params, expression, source. |
| **fdd_run_log** | run_ts, status, sites_processed, faults_written (last FDD run for UI). |
| **analytics_motor_runtime** | site_id, period_start, period_end, runtime_hours (data-model driven). |
| **host_metrics** | Hypertable: ts, hostname, mem_*, swap_*, load_1/5/15. |
| **container_metrics** | Hypertable: ts, container_name, cpu_pct, mem_*, pids, net_*, block_*. |
| **disk_metrics** | Hypertable: ts, hostname, mount_path, total_bytes, used_bytes, free_bytes. |
| **bacnet_write_audit** | Audit log for BACnet writes (point_id, value, source, ts, success, reason). |

### Cascade deletes

- **Site** → equipment, points, timeseries_readings, ingest_jobs (and thus fault_results, fault_events, etc. keyed by site).
- **Equipment** → points (and related timeseries).
- **Point** → timeseries_readings, bacnet_write_audit.

So deleting a site removes all its equipment, points, and their timeseries. See [Danger zone — CRUD deletes](../howto/danger_zone#crud-deletes--cascade-behavior).

### Adding or changing schema

1. Add a new migration file in `stack/sql/` with the next number (e.g. `016_my_feature.sql`).
2. Use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, and `SELECT create_hypertable(..., if_not_exists => TRUE)` so the migration is idempotent.
3. Document the table in this section and in the [Technical reference](technical_reference#database-schema-timescaledb) table.
4. Re-run bootstrap or apply migrations (bootstrap runs all `stack/sql/*.sql` in order).

---

## Where to go next

- **Environment variables, unit tests, BACnet scrape, data model API, bootstrap, LLM tagging:** [Technical reference](technical_reference).
- **Running tests:** `pytest open_fdd/tests/ -v`. See [Technical reference — Unit tests](technical_reference#unit-tests).
- **New SQL migrations and operations:** [Operations — New SQL migrations](../howto/operations#new-sql-migrations).
- **Grafana and SQL recipes:** [Grafana SQL cookbook](../howto/grafana_cookbook).
