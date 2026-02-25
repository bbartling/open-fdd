---
title: Grafana SQL cookbook
parent: How-to Guides
nav_order: 40
---


# Grafana SQL cookbook — Weather + BACnet + Fault overlays

This cheat sheet extends the existing Grafana SQL cookbook with **weather-focused dashboards** and two “combo” patterns:

1) **BACnet + Weather** on the same chart  
2) **BACnet + Weather + Fault** on the same chart (fault as a line, bars, or annotations)

Open-FDD provisions a **PostgreSQL/TimescaleDB** datasource for Grafana (UID `openfdd_timescale`). You build panels manually using SQL against the Open-FDD database.

> Key idea: everything becomes easy if you always return the “Grafana time series triple”:
>
> - `time` (timestamp)
> - `value` (number)
> - `metric` (string label; becomes series name)

---

## Datasource

If you run Docker stack, datasource is usually already provisioned:

- **Name:** TimescaleDB  
- **UID:** `openfdd_timescale`  
- **Type:** PostgreSQL  
- **Database:** `openfdd`  
- **Host:** `db:5432` (from Grafana container)  
- **User/Pass:** `postgres` / `postgres`

---

## Weather data model (how Open-FDD stores it)

Weather time series are stored the same way as BACnet points:

- `points` holds the “point registry”
- `timeseries_readings` holds the actual time series values

**Typical distinction:**
- **BACnet points:** `points.bacnet_device_id IS NOT NULL`
- **Weather points:** `points.bacnet_device_id IS NULL`
- Weather series often use `points.external_id` like:
  - `temp_f`, `rh_pct`, `dewpoint_f`, `wind_mph`, `gust_mph`, `cloud_pct`, etc.

> If your weather uses `weather_hourly_raw`, you can chart that too, but the easiest Grafana approach is using `points + timeseries_readings` because it matches your BACnet queries.

---

## Weather dashboard recipe

### Variables (dropdowns)

Create variables in **Dashboard → Settings → Variables**.

#### 1) `site` (weather-capable sites)

```sql
SELECT s.name AS __text, s.id::text AS __value
FROM sites s
WHERE EXISTS (
  SELECT 1
  FROM points p
  WHERE p.site_id = s.id
    AND p.bacnet_device_id IS NULL
)
ORDER BY s.name;
````

#### 2) `wx_point` (multi-select weather points for that site)

```sql
SELECT p.external_id AS __text, p.external_id AS __value
FROM points p
WHERE p.site_id::text = '$site'
  AND p.bacnet_device_id IS NULL
ORDER BY p.external_id;
```

Settings:

* **Multi-value:** ✅ ON
* **Include All:** optional

---

### Panel: Weather (multi-point) time series

Panel settings:

* Visualization: **Time series**
* Query **Format: Time series** (not Table)

```sql
SELECT
  time_bucket(
    make_interval(secs => ($__interval_ms / 1000)::int),
    tr.ts
  ) AS time,
  avg(tr.value) AS value,
  p.external_id AS metric
FROM timeseries_readings tr
JOIN points p ON p.id = tr.point_id
WHERE $__timeFilter(tr.ts)
  AND p.site_id::text = '$site'
  AND p.bacnet_device_id IS NULL
  AND p.external_id IN (${wx_point:sqlstring})
GROUP BY 1, 3
ORDER BY 1, 3;
```

---

### Panels: Weather “status” stats (optional)

**Weather data status** (OK if any weather data in last 25 hours)

```sql
SELECT COALESCE(
  (SELECT CASE WHEN MAX(tr.ts) > NOW() - INTERVAL '25 hours'
               THEN 'ok' ELSE 'stale' END
   FROM timeseries_readings tr
   JOIN points p ON tr.point_id = p.id
   WHERE p.bacnet_device_id IS NULL),
  'stale'
) AS value;
```

**Last weather time** (stat panel; unit: `dateTimeFromNow`)

```sql
SELECT EXTRACT(EPOCH FROM (
  SELECT MAX(tr.ts)
  FROM timeseries_readings tr
  JOIN points p ON tr.point_id = p.id
  WHERE p.bacnet_device_id IS NULL
))::bigint * 1000 AS value;
```

---

## Combine BACnet + Weather on one chart

There are two common approaches:

### Approach A (recommended): Single panel, UNION ALL, series label prefixes

Create variables:

#### 1) `device` (BACnet device)

```sql
SELECT DISTINCT p.bacnet_device_id::text AS __text,
                p.bacnet_device_id::text AS __value
FROM points p
WHERE p.site_id::text = '$site'
  AND p.bacnet_device_id IS NOT NULL
ORDER BY 1;
```

#### 2) `bac_point` (multi-select BACnet points)

```sql
SELECT p.external_id AS __text, p.external_id AS __value
FROM points p
WHERE p.site_id::text = '$site'
  AND p.bacnet_device_id::text = '$device'
  AND COALESCE(p.polling, true) = true
ORDER BY p.external_id;
```

#### 3) `wx_point` (multi-select weather points) — reuse from weather recipe above

---

### Panel: BACnet + Weather (combined series)

Panel settings:

* Visualization: **Time series**
* Query **Format: Time series**

```sql
WITH bucketed AS (
  -- BACnet series
  SELECT
    time_bucket(
      make_interval(secs => ($__interval_ms / 1000)::int),
      tr.ts
    ) AS time,
    avg(tr.value) AS value,
    'BACnet: ' || p.external_id AS metric
  FROM timeseries_readings tr
  JOIN points p ON p.id = tr.point_id
  WHERE $__timeFilter(tr.ts)
    AND p.site_id::text = '$site'
    AND p.bacnet_device_id::text = '$device'
    AND p.external_id IN (${bac_point:sqlstring})
  GROUP BY 1, p.external_id

  UNION ALL

  -- Weather series
  SELECT
    time_bucket(
      make_interval(secs => ($__interval_ms / 1000)::int),
      tr.ts
    ) AS time,
    avg(tr.value) AS value,
    'Weather: ' || p.external_id AS metric
  FROM timeseries_readings tr
  JOIN points p ON p.id = tr.point_id
  WHERE $__timeFilter(tr.ts)
    AND p.site_id::text = '$site'
    AND p.bacnet_device_id IS NULL
    AND p.external_id IN (${wx_point:sqlstring})
  GROUP BY 1, p.external_id
)
SELECT time, value, metric
FROM bucketed
ORDER BY time, metric;
```

**Notes:**

* This produces multiple series with names like `BACnet: SA-T` and `Weather: temp_f`.
* If units differ (°F vs % vs command), consider:

  * separate panels, or
  * assign a second Y-axis using Field Overrides in Grafana.

---

### Approach B: Two queries in one panel (A = BACnet, B = Weather)

You can also add two queries (Query A and Query B) in a single panel. Each query returns its own time/value/metric series. This avoids one giant SQL, but the UNION approach is easier to copy/paste as a single “combo recipe.”

---

## Combine BACnet + Weather + Fault on one chart

There are three ways to show faults in the same visualization:

1. **Fault as a separate time series** (line or bars)
2. **Fault as annotations** (vertical markers on the time series)
3. **Fault events** as shaded regions (using `fault_events` + annotations)

Below are two practical patterns.

---

### Pattern 1: Fault as a time series (line/bars) + BACnet + Weather

Add variable:

#### `fault_id` (multi-select faults to overlay)

```sql
SELECT DISTINCT fr.fault_id AS __text, fr.fault_id AS __value
FROM fault_results fr
ORDER BY fr.fault_id;
```

Optional: add `equipment` variable, if you want to bind fault results to a specific AHU/VAV:

```sql
SELECT DISTINCT e.name AS __text, e.name AS __value
FROM equipment e
WHERE e.site_id::text = '$site'
ORDER BY e.name;
```

---

### Panel: BACnet + Weather + Fault (all series)

Panel settings:

* Visualization: **Time series**
* Query **Format: Time series**
* Consider setting the fault series draw style to **bars** via overrides.

```sql
WITH series AS (
  -- BACnet
  SELECT
    time_bucket(
      make_interval(secs => ($__interval_ms / 1000)::int),
      tr.ts
    ) AS time,
    avg(tr.value) AS value,
    'BACnet: ' || p.external_id AS metric
  FROM timeseries_readings tr
  JOIN points p ON p.id = tr.point_id
  WHERE $__timeFilter(tr.ts)
    AND p.site_id::text = '$site'
    AND p.bacnet_device_id::text = '$device'
    AND p.external_id IN (${bac_point:sqlstring})
  GROUP BY 1, p.external_id

  UNION ALL

  -- Weather
  SELECT
    time_bucket(
      make_interval(secs => ($__interval_ms / 1000)::int),
      tr.ts
    ) AS time,
    avg(tr.value) AS value,
    'Weather: ' || p.external_id AS metric
  FROM timeseries_readings tr
  JOIN points p ON p.id = tr.point_id
  WHERE $__timeFilter(tr.ts)
    AND p.site_id::text = '$site'
    AND p.bacnet_device_id IS NULL
    AND p.external_id IN (${wx_point:sqlstring})
  GROUP BY 1, p.external_id

  UNION ALL

  -- Fault overlay (flag counts per bucket)
  SELECT
    time_bucket(
      make_interval(secs => ($__interval_ms / 1000)::int),
      fr.ts
    ) AS time,
    SUM(fr.flag_value)::float AS value,
    'Fault: ' || fr.fault_id AS metric
  FROM fault_results fr
  JOIN equipment e ON e.id = fr.equipment_id
  WHERE $__timeFilter(fr.ts)
    AND e.site_id::text = '$site'
    -- If you add equipment variable by name:
    -- AND ('$equipment' = '' OR e.name = '$equipment')
    AND fr.fault_id IN (${fault_id:sqlstring})
  GROUP BY 1, fr.fault_id
)
SELECT time, value, metric
FROM series
ORDER BY time, metric;
```

**Grafana overrides suggestion:**

* For series name matching `Fault: *`

  * Draw style: **Bars**
  * Fill opacity: moderate
  * Y-axis: Right (optional)

---

### Pattern 2: Fault events as annotations (recommended “operator UX”)

Instead of adding faults as lines, add **annotations** so your BACnet/Weather lines stay clean and you see “fault starts” and “fault ends”.

In Grafana:

* Panel → **Annotations** (or Dashboard-level annotations)

Annotation query example (fault event windows):

```sql
SELECT
  fe.start_ts AS time,
  fe.end_ts AS timeend,
  fe.fault_id AS text,
  e.name AS tags
FROM fault_events fe
JOIN equipment e ON e.id = fe.equipment_id
WHERE e.site_id::text = '$site'
  AND fe.start_ts <= $__timeTo()
  AND fe.end_ts >= $__timeFrom()
ORDER BY fe.start_ts;
```

This will draw shaded regions/markers (depending on Grafana version) to indicate fault episodes.

---

## Unit + scale tips (important when combining)

When combining BACnet + Weather + Fault:

* Temperatures, commands, pressures, and binary flags will not share a natural unit.
* Practical options:

  1. **Two Y-axes**: put temps on left, %/commands on right
  2. **Separate panels**: one for temps, one for damper/valves, one for faults
  3. **Normalize**: only if you truly want relative comparisons

---

## “Gotchas” checklist (so series don’t jumble)

* ✅ Query **Format = Time series** (not Table)
* ✅ Use `${var:sqlstring}` for multi-select variables
* ✅ Return columns named `time`, `value`, and `metric`
* ✅ Don’t override display name to a static value in Grafana panel settings

---

## Copy/paste variable set (minimal combo dashboard)

**site**

```sql
SELECT s.name AS __text, s.id::text AS __value
FROM sites s
ORDER BY s.name;
```

**device**

```sql
SELECT DISTINCT p.bacnet_device_id::text AS __text, p.bacnet_device_id::text AS __value
FROM points p
WHERE p.site_id::text = '$site'
  AND p.bacnet_device_id IS NOT NULL
ORDER BY 1;
```

**bac_point** (multi)

```sql
SELECT p.external_id AS __text, p.external_id AS __value
FROM points p
WHERE p.site_id::text = '$site'
  AND p.bacnet_device_id::text = '$device'
ORDER BY p.external_id;
```

**wx_point** (multi)

```sql
SELECT p.external_id AS __text, p.external_id AS __value
FROM points p
WHERE p.site_id::text = '$site'
  AND p.bacnet_device_id IS NULL
ORDER BY p.external_id;
```

**fault_id** (multi)

```sql
SELECT DISTINCT fr.fault_id AS __text, fr.fault_id AS __value
FROM fault_results fr
ORDER BY fr.fault_id;
```

