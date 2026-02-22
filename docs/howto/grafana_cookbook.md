---
title: Grafana SQL cookbook
parent: How-to Guides
nav_order: 40
---

# Grafana SQL cookbook

Open-FDD provisions **only a PostgreSQL/TimescaleDB datasource** for Grafana. No dashboards are prebuilt. This cookbook shows how to set up the datasource (if needed) and how to build dashboards yourself using SQL against the Open-FDD database. For RDF/SPARQL validation of the data model (sites, equipment, points, BACnet, config), see the [SPARQL cookbook](../modeling/sparql_cookbook).

## Datasource

### When it’s already set up (Docker)

If you run the stack with `./scripts/bootstrap.sh` or `docker compose -f platform/docker-compose.yml up -d`, Grafana is provisioned with one datasource:

- **Name:** TimescaleDB  
- **UID:** `openfdd_timescale` (use this in panels)  
- **Type:** PostgreSQL  
- **Database:** `openfdd`  
- **Connection:** From the Grafana container, host is `db` (Docker service name); port 5432, user `postgres`, password `postgres`.

In panel JSON or the UI, select the datasource with UID `openfdd_timescale`.

### If you need to add the datasource yourself

1. In Grafana: **Connections** → **Data sources** → **Add data source** → **PostgreSQL**.
2. **Host:** Your DB host (e.g. `localhost:5432` from host, or `db:5432` from another container).
3. **Database:** `openfdd`
4. **User / Password:** `postgres` / `postgres` (or your DB credentials).
5. **TLS/SSL:** Disable if local.
6. Save & test. Optionally set **UID** to `openfdd_timescale` so it matches the cookbook.

---

## Database tables to query

Grafana talks to the same database as the API and scrapers. Use these tables in raw SQL.

### BACnet / data model

| Table | Key columns | Use for |
|-------|-------------|--------|
| **sites** | `id` (uuid), `name` | Site list for variables and filters. |
| **points** | `id`, `site_id`, `external_id`, `object_name`, `bacnet_device_id`, `object_identifier`, `polling`, `equipment_id` | BACnet/data-model points. Points with `bacnet_device_id IS NOT NULL` are BACnet; scraper polls those with `polling = true`. |
| **timeseries_readings** | `ts`, `point_id`, `value`, `site_id` | Time series. Join to `points` on `point_id` for labels and filters. BACnet scraper writes here. |

### Faults

| Table | Key columns | Use for |
|-------|-------------|--------|
| **fault_results** | `ts`, `site_id`, `equipment_id`, `fault_id`, `flag_value` | FDD fault flags over time (one row per ts/equipment/fault). |
| **fault_events** | `start_ts`, `end_ts`, `fault_id`, `equipment_id` | Fault episodes for annotations. |
| **fdd_run_log** | `run_ts`, `status`, `sites_processed`, `faults_written` | Last FDD run; use for “Fault Runner Status” and “Last ran”. |

### Computer / host resources

| Table | Key columns | Use for |
|-------|-------------|--------|
| **host_metrics** | `ts`, `hostname`, `mem_used_bytes`, `mem_available_bytes`, `load_1`, `load_5`, `load_15`, `swap_used_bytes`, `swap_total_bytes` | Host memory and load. |
| **container_metrics** | `ts`, `container_name`, `cpu_pct`, `mem_usage_bytes`, `mem_pct`, `pids` | Per-container CPU and memory. |

### Weather and analytics

| Table | Key columns | Use for |
|-------|-------------|--------|
| **timeseries_readings** + **points** | Weather points have `p.bacnet_device_id IS NULL`; `external_id` like `temp_f`, `rh_pct`, etc. | Weather time series (Open-Meteo scraper). |
| **analytics_motor_runtime** | `site_id`, `point_external_id`, `point_brick_type`, `runtime_hours`, `period_start`, `period_end`, `updated_at` | Motor runtime analytics (populated via API or cron). |

### Time range in SQL

- Use **`$__timeFilter(ts)`** in `WHERE` so the panel respects the dashboard time picker (e.g. `WHERE $__timeFilter(tr.ts)`).
- For time series panels, return **`time`** (timestamp) and **`value`** (number); optional **`metric`** for series name.
- For “last value” or stat panels, return a single row with a **`value`** column (and optionally **`time`** for “dateTimeFromNow” units).

---

## Recipe 1: BACnet timeseries dashboard

**Goal:** Scraper status, last BACnet data time, count of polling points, and time series by site/device/point.

### Variables (dropdowns)

Create three **Query** variables on the datasource `openfdd_timescale`. Query must return `__text` (label) and `__value` (value used in SQL).

**1. Site**

```sql
SELECT s.name AS __text, s.id::text AS __value
FROM sites s
WHERE EXISTS (
  SELECT 1 FROM points p
  WHERE p.site_id = s.id
    AND p.bacnet_device_id IS NOT NULL
    AND COALESCE(p.polling, true) = true
)
ORDER BY s.name
```

**2. Device** (depends on `$site`)

```sql
SELECT DISTINCT bacnet_device_id::text AS __text, bacnet_device_id::text AS __value
FROM points
WHERE site_id::text = '$site'
  AND bacnet_device_id IS NOT NULL
  AND COALESCE(polling, true) = true
ORDER BY bacnet_device_id::text
```

**3. Point** (depends on `$site`, `$device`)

```sql
SELECT COALESCE(object_name, external_id) AS __text, external_id AS __value
FROM points
WHERE site_id::text = '$site'
  AND bacnet_device_id::text = '$device'
  AND COALESCE(polling, true) = true
ORDER BY COALESCE(object_name, external_id)
```

### Panels (SQL)

**BACnet scraper status** (stat; OK if any BACnet reading in last 15 min)

```sql
SELECT COALESCE(
  (SELECT CASE WHEN MAX(tr.ts) > NOW() - INTERVAL '15 minutes' THEN 'ok' ELSE 'stale' END
   FROM timeseries_readings tr
   JOIN points p ON tr.point_id = p.id
   WHERE p.bacnet_device_id IS NOT NULL),
  'stale'
) AS value
```

**Last BACnet data** (stat; unit: dateTimeFromNow)

```sql
SELECT EXTRACT(EPOCH FROM (
  SELECT MAX(tr.ts)
  FROM timeseries_readings tr
  JOIN points p ON tr.point_id = p.id
  WHERE p.bacnet_device_id IS NOT NULL
))::bigint * 1000 AS value
```

**BACnet points (polling)** (stat; count)

```sql
SELECT COUNT(*)::bigint AS value
FROM points
WHERE bacnet_device_id IS NOT NULL
  AND COALESCE(polling, true) = true
```

**All BACnet points (any site)** (time series)

```sql
SELECT tr.ts AS time,
       p.external_id || ' (dev ' || p.bacnet_device_id || ')' AS metric,
       tr.value
FROM timeseries_readings tr
JOIN points p ON tr.point_id = p.id
WHERE $__timeFilter(tr.ts)
  AND p.bacnet_device_id IS NOT NULL
ORDER BY tr.ts ASC
```

**By device** (time series; use `$site`, `$device`)

```sql
SELECT tr.ts AS time, p.external_id AS metric, tr.value
FROM timeseries_readings tr
JOIN points p ON tr.point_id = p.id
WHERE $__timeFilter(tr.ts)
  AND p.site_id::text = '$site'
  AND p.bacnet_device_id::text = '$device'
ORDER BY tr.ts ASC
```

**Single point** (time series; use `$site`, `$device`, `$point`)

```sql
SELECT tr.ts AS time, tr.value
FROM timeseries_readings tr
JOIN points p ON tr.point_id = p.id
WHERE $__timeFilter(tr.ts)
  AND p.site_id::text = '$site'
  AND p.bacnet_device_id::text = '$device'
  AND p.external_id = '$point'
ORDER BY tr.ts ASC
```

---

## Recipe 2: Fault Results dashboard

**Goal:** Fault Runner status, last run time, weather-fault count, total fault count, and fault time series.

### Variable

**equipment** (Query; optional filter)

```sql
SELECT equipment_id AS __text, equipment_id AS __value
FROM fault_results
WHERE equipment_id != ''
GROUP BY equipment_id
UNION ALL
SELECT 'All', ''
ORDER BY __value
```

### Panels

**Fault Runner Status** (stat; one value: ok / error / never)

```sql
SELECT COALESCE(
  (SELECT run_ts FROM fdd_run_log ORDER BY run_ts DESC LIMIT 1),
  NOW()
) AS time,
COALESCE(
  (SELECT status FROM fdd_run_log ORDER BY run_ts DESC LIMIT 1),
  'never'
) AS value
```

**Fault Runner — Last ran** (stat; unit: dateTimeFromNow)

```sql
SELECT (SELECT EXTRACT(EPOCH FROM run_ts)::bigint * 1000
        FROM fdd_run_log ORDER BY run_ts DESC LIMIT 1) AS value
```

**Weather faults (time range)** (stat; count in range)

```sql
SELECT COALESCE(SUM(flag_value), 0)::bigint AS value
FROM fault_results
WHERE fault_id IN ('fault_temp_stuck','fault_rh_out_of_range','fault_temp_spike','fault_gust_lt_wind')
  AND $__timeFilter(ts)
```

**Fault count (time range)** (stat)

```sql
SELECT COALESCE(SUM(flag_value), 0)::bigint AS value
FROM fault_results
WHERE $__timeFilter(ts)
```

**Fault flags by fault_id** (time series)

```sql
SELECT ts AS time, fault_id AS metric, SUM(flag_value) AS value
FROM fault_results
WHERE $__timeFilter(ts)
GROUP BY ts, fault_id
ORDER BY ts
```

**Faults by equipment** (time series; optional `$equipment` filter)

```sql
SELECT ts AS time, fault_id AS metric, flag_value AS value
FROM fault_results
WHERE ('$equipment' = '' OR equipment_id = '$equipment')
  AND $__timeFilter(ts)
ORDER BY ts
```

---

## Recipe 3: Fault Analytics (motor runtime)

**Goal:** Motor runtime stat and table by site; data comes from `analytics_motor_runtime` (filled via `GET /analytics/motor-runtime` or cron).

### Variable

**site** (Query; include “All”)

```sql
SELECT name AS __text, name AS __value FROM sites
UNION ALL
SELECT 'All', 'All'
ORDER BY __value
```

### Panels

**Motor runtime (h)** (stat)

```sql
SELECT COALESCE(SUM(runtime_hours)::text, 'NO DATA') AS value
FROM analytics_motor_runtime
WHERE (site_id = '$site' OR '$site' = 'All')
  AND period_start <= $__timeTo()::date
  AND period_end >= $__timeFrom()::date
```

**Motor runtime by site** (table)

```sql
SELECT site_id, point_external_id, point_brick_type, runtime_hours, period_start, period_end, updated_at
FROM analytics_motor_runtime
WHERE period_start <= $__timeTo()::date
  AND period_end >= $__timeFrom()::date
ORDER BY site_id
```

---

## Recipe 4: Weather (Open-Meteo) dashboard

**Goal:** Weather data status, last weather time, and time series for temp/humidity etc. Weather points are in `points` with `bacnet_device_id IS NULL`; series in `timeseries_readings`.

### Variable

**site** (sites that have non-BACnet points, e.g. weather)

```sql
SELECT s.name AS __text, s.id::text AS __value
FROM sites s
WHERE EXISTS (
  SELECT 1 FROM points p
  WHERE p.site_id = s.id AND p.bacnet_device_id IS NULL
)
ORDER BY s.name
```

### Panels

**Weather data status** (stat; OK if any non-BACnet reading in last 25 h)

```sql
SELECT COALESCE(
  (SELECT CASE WHEN MAX(tr.ts) > NOW() - INTERVAL '25 hours' THEN 'ok' ELSE 'stale' END
   FROM timeseries_readings tr
   JOIN points p ON tr.point_id = p.id
   WHERE p.bacnet_device_id IS NULL),
  'stale'
) AS value
```

**Last weather data** (stat; unit: dateTimeFromNow)

```sql
SELECT EXTRACT(EPOCH FROM (
  SELECT MAX(tr.ts)
  FROM timeseries_readings tr
  JOIN points p ON tr.point_id = p.id
  WHERE p.bacnet_device_id IS NULL
))::bigint * 1000 AS value
```

**Temperature & humidity** (time series; use `$site`; adjust `external_id` list as needed)

```sql
SELECT tr.ts AS time, p.external_id AS metric, tr.value
FROM timeseries_readings tr
JOIN points p ON tr.point_id = p.id
WHERE $__timeFilter(tr.ts)
  AND p.site_id::text = '$site'
  AND p.external_id IN ('temp_f', 'rh_pct')
ORDER BY tr.ts ASC
```

Add more panels for other keys (e.g. `dewpoint_f`, `wind_mph`, `gust_mph`, `wind_dir_deg`, `shortwave_wm2`, `cloud_pct`) by changing the `IN (...)` list or using a single series with `p.external_id = '$metric'` and a metric variable.

---

## Recipe 5: System Resources (host & containers)

**Goal:** Host memory, load, swap; container memory and CPU time series; latest container table. No variables required.

### Panels

**Host memory used** (stat; GB)

```sql
SELECT (mem_used_bytes / 1024.0 / 1024 / 1024)::numeric(10,2) AS value
FROM host_metrics
WHERE $__timeFilter(ts)
ORDER BY ts DESC
LIMIT 1
```

**Host memory available** (stat; GB)

```sql
SELECT (mem_available_bytes / 1024.0 / 1024 / 1024)::numeric(10,2) AS value
FROM host_metrics
WHERE $__timeFilter(ts)
ORDER BY ts DESC
LIMIT 1
```

**Load average (1m)** (stat)

```sql
SELECT load_1::numeric(10,2) AS value
FROM host_metrics
WHERE $__timeFilter(ts)
ORDER BY ts DESC
LIMIT 1
```

**Swap used** (stat; GB)

```sql
SELECT (swap_used_bytes / 1024.0 / 1024 / 1024)::numeric(10,2) AS value
FROM host_metrics
WHERE $__timeFilter(ts)
ORDER BY ts DESC
LIMIT 1
```

**Host memory (GB)** (time series; used + available)

```sql
SELECT ts AS time, 'used' AS metric, (mem_used_bytes / 1024.0 / 1024 / 1024) AS value
FROM host_metrics WHERE $__timeFilter(ts)
UNION ALL
SELECT ts, 'available', (mem_available_bytes / 1024.0 / 1024 / 1024)
FROM host_metrics WHERE $__timeFilter(ts)
ORDER BY time
```

**Host load average** (time series)

```sql
SELECT ts AS time, 'load_1m' AS metric, load_1 AS value FROM host_metrics WHERE $__timeFilter(ts)
UNION ALL
SELECT ts, 'load_5m', load_5 FROM host_metrics WHERE $__timeFilter(ts)
UNION ALL
SELECT ts, 'load_15m', load_15 FROM host_metrics WHERE $__timeFilter(ts)
ORDER BY time
```

**Container memory (MB)** (time series)

```sql
SELECT ts AS time, container_name AS metric, (mem_usage_bytes / 1024.0 / 1024) AS value
FROM container_metrics
WHERE $__timeFilter(ts)
ORDER BY ts
```

**Container CPU %** (time series)

```sql
SELECT ts AS time, container_name AS metric, cpu_pct AS value
FROM container_metrics
WHERE $__timeFilter(ts)
ORDER BY ts
```

**Containers (latest)** (table)

```sql
SELECT container_name,
       ROUND(cpu_pct::numeric, 1) AS "CPU %",
       ROUND((mem_usage_bytes/1024.0/1024)::numeric, 1) AS "Mem MB",
       mem_pct AS "Mem %",
       pids AS "PIDs"
FROM container_metrics
WHERE ts = (SELECT MAX(ts) FROM container_metrics)
ORDER BY mem_usage_bytes DESC
```

---

## Quick reference

- **Datasource UID:** `openfdd_timescale` (PostgreSQL, database `openfdd`).
- **Variables:** Query type; return columns `__text` and `__value`; reference in SQL as `'$name'`.
- **Time filter:** Use `$__timeFilter(ts)` in `WHERE`; time series need columns `time` and `value` (and optional `metric`).
- **BACnet:** `points.bacnet_device_id IS NOT NULL` and `COALESCE(polling, true) = true` for the set the scraper polls; join `timeseries_readings` to `points` on `point_id`.
- **Faults:** `fault_results` for time series; `fdd_run_log` for runner status and last run.
- **Resources:** `host_metrics` and `container_metrics`; written by the host-stats container.
