---
title: Custom Grafana dashboards
parent: How-to Guides
nav_order: 45
---

# Building custom Grafana dashboards

Open-FDD provisions Grafana from config under `platform/grafana/`. You can add or edit dashboards without rebuilding any container. This page explains how.

## Where dashboards live

| Path | Purpose |
|------|---------|
| `platform/grafana/dashboards/*.json` | Dashboard definitions (one file per dashboard). Any `.json` here is loaded at Grafana startup. |
| `platform/grafana/provisioning/dashboards/dashboards.yml` | Provider config: loads from `/var/lib/grafana/dashboards` (that path is mounted from `dashboards/`). |
| `platform/grafana/provisioning/datasources/datasource.yml` | TimescaleDB datasource (uid: **openfdd_timescale**). |

The Grafana container **mounts** these dirs from the host, so editing or adding a JSON file on disk is enough; restart Grafana to reload: `docker restart openfdd_grafana` (or run `./scripts/bootstrap.sh`).

## BACnet dashboard: graph-based and SPARQL-aligned

The **BACnet Timeseries** dashboard (`bacnet_timeseries.json`) shows all BACnet data and last-scrape state. It is **graph-based** in the sense that the same points that appear in the Brick/SPARQL data model (TTL, `ofdd:polling true`) are the ones in the database that the scraper polls and that Grafana queries. The API keeps the DB in sync with the graph (import/export, TTL serialize). Grafana does not run SPARQL directly; it queries the **PostgreSQL/TimescaleDB** tables (`points`, `timeseries_readings`, `sites`) that are the materialized view of the data model.

- **All BACnet data:** The panels “All BACnet points (any site)”, “By device”, and “Single point” show every BACnet series that has data in the time range. The dropdowns (site, device, point) list exactly the points with `bacnet_device_id`, `object_identifier`, and `polling = true` — the same set as SPARQL `ofdd:polling true` and the scraper load.
- **Last scrape messages:** “BACnet scraper status” (OK/Stale) and “Last BACnet data” (timestamp) represent the last successful scrape: OK if any BACnet reading exists in the last 15 minutes, and the time of the most recent reading. Scraper log text (e.g. “Scrape cycle: N rows”) is not stored in the DB; the dashboard reflects scrape health via presence and recency of data.
- **BACnet points (polling):** The count stat matches the number of points the scraper loads and the count from `POST /data-model/sparql` with `SELECT (COUNT(?pt) AS ?n) WHERE { ?pt ofdd:polling true . }` (see `tools/graph_and_crud_test.py` step [25b]).

So the dashboard is fully aligned with the graph/SPARQL data model; all BACnet data and last-scrape information that the system stores appear there.

## Datasource

All panels use the **PostgreSQL/TimescaleDB** datasource:

- **UID:** `openfdd_timescale` (use this in panel `datasource.uid` in JSON).
- **Database:** `openfdd`.
- **Connection:** From the Grafana container, host is `db` (Docker Compose service name).

In panel JSON:

```json
"datasource": { "type": "postgres", "uid": "openfdd_timescale" }
```

## Tables you can query

Use these in **raw SQL** panels (Postgres data source):

| Table | Key columns | Use for |
|-------|-------------|---------|
| **timeseries_readings** | `ts`, `point_id`, `value`, `site_id` | BACnet/weather time series. Join `points` for `external_id`, `site_id`, `bacnet_device_id`. |
| **points** | `id`, `site_id`, `external_id`, `bacnet_device_id`, `object_identifier`, `equipment_id` | Labels, site/device/point dropdowns. |
| **sites** | `id`, `name` | Site list for variables. |
| **fault_results** | `ts`, `site_id`, `equipment_id`, `fault_id`, `flag_value` | FDD fault flags over time. |
| **fault_events** | `start_ts`, `end_ts`, `fault_id`, `equipment_id` | Fault episodes (annotations). |
| **host_metrics** | `ts`, `hostname`, `mem_used_bytes`, `mem_available_bytes`, `load_1`, `load_5`, `load_15`, `swap_*` | Host memory and load. |
| **container_metrics** | `ts`, `container_name`, `cpu_pct`, `mem_usage_bytes`, `mem_pct`, `pids` | Per-container CPU/memory. |
| **fdd_run_log** | `run_ts`, `status`, `sites_processed`, `faults_written` | Last FDD run status. |
| **weather_hourly_raw** | `ts`, `site_id`, `point_key`, `value` | Weather time series (temp_f, rh_pct, etc.). |

## Time range and macros

- Use **`$__timeFilter(ts)`** in SQL so the panel respects the dashboard time picker. Example: `WHERE $__timeFilter(tr.ts)`.
- For time series panels, return columns **`time`** (timestamp) and **`value`** (number); optional **`metric`** for series name. Example:

```sql
SELECT tr.ts AS time, p.external_id AS metric, tr.value
FROM timeseries_readings tr
JOIN points p ON tr.point_id = p.id
WHERE $__timeFilter(tr.ts) AND p.site_id::text = '$site'
ORDER BY tr.ts
```

## Variables (dropdowns)

Variables are defined in the dashboard JSON under `templating.list`. Use a **Query** type with the Postgres datasource. The query must return two columns:

- **`__text`** — Label shown in the dropdown.
- **`__value`** — Value substituted when the user selects (e.g. in `$site`).

Example (sites that have BACnet points):

```sql
SELECT s.name AS __text, s.id::text AS __value
FROM sites s
WHERE EXISTS (SELECT 1 FROM points p WHERE p.site_id = s.id AND p.bacnet_device_id IS NOT NULL)
ORDER BY s.name
```

Example (equipment IDs for fault_results):

```sql
SELECT equipment_id AS __text, equipment_id AS __value
FROM fault_results
WHERE equipment_id != ''
GROUP BY equipment_id
ORDER BY __value
```

In panel SQL, reference the variable as `'$variable_name'` (e.g. `'$site'`, `'$device'`).

## Adding a new dashboard

### Option A: Copy and edit an existing one

1. Copy an existing JSON from `platform/grafana/dashboards/` (e.g. `bacnet_timeseries.json`).
2. Rename the file (e.g. `my_custom.json`).
3. Edit the JSON: set **`uid`** and **`title`** to unique values (e.g. `"uid": "my-custom"`, `"title": "My Custom"`). If you leave a duplicate `uid`, one dashboard can overwrite the other.
4. Change panels, queries, and variables as needed. Keep `datasource.uid` as `openfdd_timescale`.
5. Restart Grafana: `docker restart openfdd_grafana`. The new dashboard appears under the **Open-FDD** folder.

### Option B: Build in the UI, then export

1. Open Grafana (e.g. http://localhost:3000), create a new dashboard, add panels and variables using the **openfdd_timescale** datasource.
2. Save the dashboard (set a name and optional folder **Open-FDD**).
3. Go to **Dashboard settings** (gear) → **JSON Model**. Copy the JSON.
4. Save to a file in `platform/grafana/dashboards/` (e.g. `my_custom.json`). Ensure the JSON has **`"uid": "some-unique-id"`** and **`"title": "My Custom"`**.
5. (Optional) If you created the dashboard in the UI, you can delete it there; after the next Grafana restart, the provisioned version from the file will appear.

Restart Grafana so the file is loaded: `docker restart openfdd_grafana`.

## Checklist

- **Datasource:** Use `uid: openfdd_timescale` in every panel.
- **Time series:** Use `$__timeFilter(ts)` (or your time column) and return `time` and `value` (and optionally `metric`).
- **Variables:** Query returns `__text` and `__value`; reference in SQL as `'$name'`.
- **Unique uid:** Each dashboard JSON should have a unique `uid` so provisioning doesn’t overwrite another dashboard.
- **No rebuild:** Only restart Grafana after adding or changing JSON files.

For dashboard issues (No data, too many sites, etc.) see [Grafana troubleshooting](grafana_troubleshooting).
