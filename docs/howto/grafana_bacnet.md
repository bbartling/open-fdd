# Grafana (TimescaleDB) — BACnet Point Time Series with Dashboard Variables

These notes document how to build a Grafana time series panel that plots **one line per selected BACnet point** (e.g., `CLG-O`, `DAP-P`, `DAP-SP`) using **dropdown variables** (no hard-coded device IDs or point names).

---

## Prereqs

### Data source
- Grafana data source type: **PostgreSQL / TimescaleDB**
- Your datasource UID (example): `openfdd_timescale`

### Required tables/columns

This panel expects the following schema pieces to exist:

- `timeseries_readings(ts, point_id, value)`  
- `points(id, external_id, bacnet_device_id, ...)`

At minimum, the query relies on:
- `timeseries_readings.ts` (timestamp)
- `timeseries_readings.value` (numeric)
- `timeseries_readings.point_id` (FK → points.id)
- `points.id`
- `points.external_id` (the BACnet “short name” used as a series label)
- `points.bacnet_device_id` (device selector)

---

## Database schema (TimescaleDB)

Schema in `platform/sql/`. **Cascade deletes:** Site → equipment, points, timeseries; equipment → points, timeseries; point → timeseries. See [Danger zone](../howto/danger_zone).

| Table | Purpose |
|-------|---------|
| **sites** | id, name, description, metadata, created_at |
| **equipment** | id, site_id, name, equipment_type, feeds_equipment_id, fed_by_equipment_id |
| **points** | id, site_id, equipment_id, external_id, brick_type, fdd_input, bacnet_device_id, object_identifier, object_name, polling |
| **timeseries_readings** | ts, point_id, value (hypertable) |
| **fault_results** | ts, site_id, equipment_id, fault_id, flag_value (hypertable) |
| **fault_events** | start_ts, end_ts, fault_id, equipment_id |
| **weather_hourly_raw** | ts, site_id, point_key, value (hypertable) |

---

## Goal

Create a panel where:
- **Device** is selected from a dropdown (Grafana variable)
- **Point(s)** are selected from a dropdown (Grafana variable; multi-select)
- The panel plots:
  - one line per selected point
  - correctly labeled in the legend

This avoids hard-coded SQL like:
- `p.bacnet_device_id = '3456789'`
- `p.external_id IN ('CLG-O','DAP-P','DAP-SP')`

---

## Step 1 — Create Dashboard Variables

Go to:

**Dashboard → Settings (gear) → Variables → New**

### Variable 1: `device`

**Type:** Query  
**Data source:** your TimescaleDB datasource  
**Name:** `device`

**Query:**
```sql
SELECT DISTINCT p.bacnet_device_id
FROM points p
WHERE p.bacnet_device_id IS NOT NULL
ORDER BY 1;
````

Recommended settings:

* **Multi-value:** OFF (usually 1 device at a time)
* **Include All:** OFF

---

### Variable 2: `point`

**Type:** Query
**Data source:** your TimescaleDB datasource
**Name:** `point`

**Query:**

```sql
SELECT p.external_id
FROM points p
WHERE p.bacnet_device_id = '$device'
ORDER BY 1;
```

Recommended settings:

* **Multi-value:** ✅ ON (so you can pick multiple points to plot)
* **Include All:** Optional (handy to plot all points on the device)

Notes:

* If you enable “Include All”, you can leave **Custom all value** blank and let Grafana expand normally.
* This variable will populate based on the selected `device`.

---

## Step 2 — Build the Panel Query

Create a new panel and select visualization:

* **Time series**

In the query editor:

* Data source: TimescaleDB
* **Format:** ✅ **Time series** (NOT Table)

### Final SQL (no hard-coded values)

```sql
SELECT
  time_bucket(
    make_interval(secs => ($__interval_ms / 1000)::int),
    tr.ts
  ) AS "time",
  avg(tr.value) AS "value",
  p.external_id AS "metric"
FROM timeseries_readings tr
JOIN points p ON p.id = tr.point_id
WHERE $__timeFilter(tr.ts)
  AND p.bacnet_device_id = '$device'
  AND p.external_id IN (${point:sqlstring})
GROUP BY 1, 3
ORDER BY 1, 3;
```

### Why this query produces multiple lines

Grafana expects a **time series-friendly shape**:

* `"time"`  → timestamp column
* `"value"` → numeric data
* `"metric"` → series label (string)

Because `metric = p.external_id`, Grafana automatically creates **one series per unique external_id**.

### Why `${point:sqlstring}` matters

When you multi-select points, Grafana must expand the variable into a safe SQL list:

* `${point:sqlstring}` becomes:
  `'CLG-O','DAP-P','DAP-SP'`

If you used `$point` directly, multi-select often breaks or becomes invalid SQL.

---

## Step 3 — Common “Why is it one jumbled line?” Fix

If the plot looks like a single weird sawtooth line, check:

1. Query editor → **Format**

   * Must be **Time series** (not Table)

2. Output columns

   * Must include:

     * `time` (timestamp)
     * `value` (number)
     * `metric` (string)

3. Panel overrides

   * Don’t force a static Display name that overwrites series labeling.

---

## Optional Enhancements

### A) Add `equipment` variable (if you want to filter by AHU/VAV)

Create variable `equipment`:

```sql
SELECT DISTINCT p.equipment_id
FROM points p
WHERE p.bacnet_device_id = '$device'
  AND p.equipment_id IS NOT NULL
ORDER BY 1;
```

Then add to the panel query:

```sql
AND p.equipment_id = '$equipment'
```

Or if you prefer names:

```sql
SELECT DISTINCT e.name
FROM equipment e
JOIN points p ON p.equipment_id = e.id
WHERE p.bacnet_device_id = '$device'
ORDER BY 1;
```

Then:

```sql
AND e.name = '$equipment'
```

---

### B) Only show “polling points” (recommended for clean charts)

If your points table uses `polling` to indicate logged points:

```sql
AND p.polling = true
```

You can apply it in the variable query too:

```sql
SELECT p.external_id
FROM points p
WHERE p.bacnet_device_id = '$device'
  AND p.polling = true
ORDER BY 1;
```

---

### C) Performance / correctness notes

* `time_bucket` with Grafana’s `$__interval_ms` makes the chart adapt to zoom level.
* `avg(tr.value)` is fine for analog points; for binary points consider `max()` or `last()` behavior depending on how you want it visualized.
* Ensure `timeseries_readings` is a hypertable for performance at scale.

---

## Quick checklist

* [ ] Variables created: `device`, `point`
* [ ] `point` is Multi-value enabled
* [ ] Panel query Format = **Time series**
* [ ] SQL uses `${point:sqlstring}`
* [ ] SQL returns `time`, `value`, `metric`

---

## Copy/paste snippets

### device variable

```sql
SELECT DISTINCT p.bacnet_device_id
FROM points p
WHERE p.bacnet_device_id IS NOT NULL
ORDER BY 1;
```

### point variable (depends on $device)

```sql
SELECT p.external_id
FROM points p
WHERE p.bacnet_device_id = '$device'
ORDER BY 1;
```

### panel SQL (time series)

```sql
SELECT
  time_bucket(
    make_interval(secs => ($__interval_ms / 1000)::int),
    tr.ts
  ) AS "time",
  avg(tr.value) AS "value",
  p.external_id AS "metric"
FROM timeseries_readings tr
JOIN points p ON p.id = tr.point_id
WHERE $__timeFilter(tr.ts)
  AND p.bacnet_device_id = '$device'
  AND p.external_id IN (${point:sqlstring})
GROUP BY 1, 3
ORDER BY 1, 3;
```


