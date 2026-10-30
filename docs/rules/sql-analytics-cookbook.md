---
title: SQL analytics cookbook
parent: Rule Cookbook
nav_order: 4
permalink: /rules/sql-analytics-cookbook/
---

# SQL analytics cookbook

Analytics SQL consumes SI-normalized values from Timescale. Where a query accepts a temperature difference, it is Δ°C; other parameter units follow their declared semantic kind. APIs return SI metadata and the SPA applies display preference. See [unit contract]({{ site.baseurl }}/modeling/units/).


Overview, RCx, and plant-health analytics are PostgreSQL on the time-series database. Rust binds `$1` to the site. The operator UI calls `/api/analytics/*`. Every query under `sql/analytics/postgres/queries/` is copied below.

| Query | File |
| --- | --- |
| `runtime` | [`motor_weekly_runtime.sql`](#runtime) |
| `bas-vs-web-oat` | [`bas_vs_web_oat.sql`](#bas-vs-web-oat) |
| `economizer` | [`economizer_deltas.sql`](#economizer) |
| `plant-health` | [`plant_health_inventory.sql`](#plant-health) |
| `mechanical-cooling` | [`mechanical_cooling_oat_bins.sql`](#mechanical-cooling) |
| `role-timeseries` | [`role_timeseries.sql`](#role-timeseries) |
| `schedule` | [`schedule_occupancy.sql`](#schedule) |
| `sensor-stats` | [`sensor_stats.sql`](#sensor-stats) |
| `sensor-faults` | [`sensor_faults_staleness.sql`](#sensor-faults) |
| `setpoints` | [`setpoints_snapshot.sql`](#setpoints) |
| `diurnal` | [`diurnal_hourly.sql`](#diurnal) |
| `topology` | [`topology_equipment.sql`](#topology) |
| `metering` | [`metering_kwh.sql`](#metering) |
| `pid-hunting` | [`pid_hunting_proxy.sql`](#pid-hunting) |
| `sql-anomaly` | [`sql_anomaly_zscore.sql`](#sql-anomaly) |
| `mv-change-point` | [`mv_change_point_daily.sql`](#mv-change-point) |
| `fuel` | [`fuel_daily.sql`](#fuel) |
| `rcx-preset-coverage` | [`rcx_preset_role_coverage.sql`](#rcx-preset-coverage) |

## runtime

`sql/analytics/postgres/queries/motor_weekly_runtime.sql`.

```sql
-- Soft-OPEN analytics pack: motor weekly runtime (status/cmd rows × 300s).
-- Parameter: $1 = site_id (building_id). Adapters bind only — no equation forks.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  'motor'::text AS kind,
  'ahu'::text AS plant_group,
  date_trunc('week', ts) AS week_start,
  to_char(date_trunc('week', ts), 'IYYY-"W"IW') AS week_label,
  (COUNT(*) FILTER (WHERE COALESCE(val, 0) > 0.05)::double precision * 300.0 / 3600.0)
    AS run_hours,
  (COUNT(*) FILTER (WHERE COALESCE(val, 0) > 0.05)::double precision * 300.0 / 3600.0)
    AS runtime_hours
FROM sample
WHERE site_id = $1
  AND (openfdd_key LIKE '%.fan_status' OR openfdd_key LIKE '%.fan_cmd'
       OR openfdd_key LIKE '%.pump_status' OR openfdd_key LIKE '%.pump_cmd')
GROUP BY 1, 4
ORDER BY 1, 4
LIMIT 500;
```

## bas-vs-web-oat

`sql/analytics/postgres/queries/bas_vs_web_oat.sql`.

```sql
-- Soft-OPEN analytics pack: BAS vs web outdoor-air temperature pairs.
-- Parameter: $1 = site_id. Timestamp join Soft-OPEN; exact point-map Soft-OPEN later.
WITH bas AS (
  SELECT ts, val AS bas_oa_t, split_part(openfdd_key, '.', 1) AS equipment_id
  FROM sample
  WHERE site_id = $1 AND openfdd_key LIKE '%.oa_t'
),
web AS (
  SELECT ts, val AS web_oa_t
  FROM sample
  WHERE site_id = $1 AND openfdd_key LIKE '%.web_oa_t'
)
SELECT b.ts, b.equipment_id, b.bas_oa_t, w.web_oa_t, (b.bas_oa_t - w.web_oa_t) AS delta_f
FROM bas b
JOIN web w ON w.ts = b.ts
ORDER BY b.ts DESC
LIMIT 2000;
```

## economizer

`sql/analytics/postgres/queries/economizer_deltas.sql`. Also used as `rcx-ahu`.

```sql
-- Per-equipment economizer deltas.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
--   $5 = minimum |OAT−RAT| (Δ°C). Rows below this are not qualified.
-- x = OAT − RAT (delta_or_f), y = MAT − RAT (delta_mr_f).
-- A row is qualified only with explicit fan_status proof, a measured MAT,
-- and |OAT−RAT| at or above $5. Missing fan status is not fan-on.
-- MAT residual is the measured MAT minus the damper mixing model, and is
-- null when the damper feedback is absent.
WITH keyed AS (
  SELECT
    ts,
    split_part(openfdd_key, '.', 1) AS equipment_id,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'oa_t') AS oa_t,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'rat') AS rat,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'mat') AS mat,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'sat') AS sat,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'oa_damper_pct') AS oa_damper_pct,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'fan_status') AS fan_status
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND split_part(openfdd_key, '.', 2) IN (
      'oa_t', 'rat', 'mat', 'sat', 'oa_damper_pct', 'fan_status'
    )
  GROUP BY ts, split_part(openfdd_key, '.', 1)
)
SELECT
  ts,
  equipment_id,
  oa_t,
  rat,
  mat,
  sat,
  oa_damper_pct,
  (oa_t - rat) AS delta_or_f,
  (mat - rat) AS delta_mr_f,
  CASE
    WHEN oa_damper_pct IS NULL THEN NULL
    ELSE mat - (rat + (oa_damper_pct / 100.0) * (oa_t - rat))
  END AS mat_resid_f,
  TRUE AS fan_on,
  TRUE AS identifiable
FROM keyed
WHERE oa_t IS NOT NULL
  AND rat IS NOT NULL
  AND mat IS NOT NULL
  AND fan_status IS NOT NULL
  AND fan_status > 0.05
  AND abs(oa_t - rat) >= $5::double precision
ORDER BY ts DESC
LIMIT 2000;
```

## plant-health

`sql/analytics/postgres/queries/plant_health_inventory.sql`. Also used as `ahu-health`, `vav-health`, `chiller-health`, `boiler-health`, `hp-health`, `zone-other-health`, `cooling-tower-health`, `sensor-health`, `ahu-temperature-health`, `ahu-pressure-health`, `ahu-economizer-health`.

```sql
-- Soft-OPEN analytics pack: plant health inventory (score unavailable until cohort SQL).
-- Parameter: $1 = building_id.
SELECT equipment_id, equip_type
FROM equipment
WHERE building_id = $1
ORDER BY equip_type NULLS LAST, equipment_id
LIMIT 500;
```

## mechanical-cooling

`sql/analytics/postgres/queries/mechanical_cooling_oat_bins.sql`.

```sql
-- Soft-OPEN analytics pack: mechanical cooling × OAT bins (elapsed hours).
-- Parameters: $1 = site_id.
-- Status/cmd proof preferred over amps (amps Soft-OPEN later). Prefer web_oa_t then oa_t.
-- kind=oat_bin Soft-OPEN consumer shape.
WITH oat AS (
  SELECT ts,
    COALESCE(
      max(val) FILTER (WHERE openfdd_key LIKE '%.web_oa_t'),
      max(val) FILTER (WHERE openfdd_key LIKE '%.oa_t')
    ) AS oat_f
  FROM sample
  WHERE site_id = $1
    AND (openfdd_key LIKE '%.web_oa_t' OR openfdd_key LIKE '%.oa_t')
  GROUP BY ts
),
comp AS (
  SELECT
    ts,
    split_part(openfdd_key, '.', 1) AS equipment_id,
    max(val) FILTER (
      WHERE openfdd_key LIKE '%.chiller_status'
         OR openfdd_key LIKE '%.compressor_status'
         OR openfdd_key LIKE '%.chiller_cmd'
         OR openfdd_key LIKE '%.compressor_cmd'
    ) AS active
  FROM sample
  WHERE site_id = $1
    AND (
      openfdd_key LIKE '%.chiller_status' OR openfdd_key LIKE '%.compressor_status'
      OR openfdd_key LIKE '%.chiller_cmd' OR openfdd_key LIKE '%.compressor_cmd'
    )
  GROUP BY ts, split_part(openfdd_key, '.', 1)
),
joined AS (
  SELECT c.equipment_id, c.ts, c.active, o.oat_f
  FROM comp c
  JOIN oat o ON o.ts = c.ts
  WHERE c.active IS NOT NULL AND o.oat_f IS NOT NULL
    AND c.active > 0.05
)
SELECT
  'oat_bin'::text AS kind,
  equipment_id,
  CASE
    WHEN oat_f < 50 THEN '<50'
    WHEN oat_f < 60 THEN '50-60'
    WHEN oat_f < 70 THEN '60-70'
    WHEN oat_f < 80 THEN '70-80'
    WHEN oat_f < 90 THEN '80-90'
    ELSE '>=90'
  END AS oat_bin,
  (COUNT(*)::double precision * 300.0 / 3600.0) AS run_hours
FROM joined
GROUP BY 1, 2, 3
ORDER BY equipment_id, oat_bin
LIMIT 500;
```

## role-timeseries

`sql/analytics/postgres/queries/role_timeseries.sql`. Also used as `rcx-vav`, `rcx-chiller`, `rcx-boiler`.

```sql
-- Soft-OPEN analytics pack: bounded role timeseries.
-- Parameters: $1 = site_id, $2 = role suffix pattern (e.g. '%.zone_t'), $3 = limit.
SELECT ts, openfdd_key, val,
       split_part(openfdd_key, '.', 1) AS equipment_id
FROM sample
WHERE site_id = $1 AND openfdd_key LIKE $2
ORDER BY ts DESC
LIMIT $3;
```

## schedule

`sql/analytics/postgres/queries/schedule_occupancy.sql`.

```sql
-- Soft-OPEN analytics pack: occupancy mode samples (calendar Soft-OPEN later).
-- Parameter: $1 = site_id.
SELECT ts, openfdd_key, val,
       split_part(openfdd_key, '.', 1) AS equipment_id
FROM sample
WHERE site_id = $1 AND openfdd_key LIKE '%.occ_mode'
ORDER BY ts DESC
LIMIT 2000;
```

## sensor-stats

`sql/analytics/postgres/queries/sensor_stats.sql`.

```sql
-- Soft-OPEN analytics pack: per-equipment/role basic sensor statistics.
-- Parameter: $1 = site_id. Full hunting/staleness Soft-OPEN later.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  min(val) AS min_val,
  max(val) AS max_val,
  avg(val) AS avg_val,
  stddev_samp(val) AS stddev_val,
  min(ts) AS first_ts,
  max(ts) AS last_ts
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 2000;
```

## sensor-faults

`sql/analytics/postgres/queries/sensor_faults_staleness.sql`.

```sql
-- Soft-OPEN analytics pack: sensor staleness / range flags (not full SV suite).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ.
WITH role_stats AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    count(*)::bigint AS n,
    max(ts) AS last_ts,
    min(val) AS min_val,
    max(val) AS max_val,
    stddev_samp(val) AS stddev_val
  FROM sample
  WHERE site_id = $1
    AND val IS NOT NULL
    AND split_part(openfdd_key, '.', 2) <> ''
  GROUP BY 1, 2
)
SELECT
  equipment_id,
  role,
  n,
  last_ts,
  min_val,
  max_val,
  stddev_val,
  CASE
    WHEN last_ts < now() - interval '24 hours' THEN 'STALE'
    WHEN stddev_val IS NOT NULL AND stddev_val = 0 AND n >= 12 THEN 'FLATLINE'
    WHEN min_val IS NOT NULL AND max_val IS NOT NULL
         AND (min_val < -40 OR max_val > 250)
         AND role LIKE '%_t' THEN 'RANGE'
    ELSE 'OK'
  END AS fault_flag
FROM role_stats
ORDER BY
  CASE
    WHEN last_ts < now() - interval '24 hours' THEN 0
    WHEN stddev_val IS NOT NULL AND stddev_val = 0 AND n >= 12 THEN 1
    WHEN min_val IS NOT NULL AND max_val IS NOT NULL
         AND (min_val < -40 OR max_val > 250)
         AND role LIKE '%_t' THEN 2
    ELSE 3
  END,
  equipment_id,
  role
LIMIT 2000;
```

## setpoints

`sql/analytics/postgres/queries/setpoints_snapshot.sql`.

```sql
-- Soft-OPEN analytics pack: latest setpoint-like roles per equipment.
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ.
WITH ranked AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    ts,
    val,
    row_number() OVER (
      PARTITION BY split_part(openfdd_key, '.', 1), split_part(openfdd_key, '.', 2)
      ORDER BY ts DESC
    ) AS rn
  FROM sample
  WHERE site_id = $1
    AND val IS NOT NULL
    AND (
      split_part(openfdd_key, '.', 2) LIKE '%_sp'
      OR split_part(openfdd_key, '.', 2) LIKE '%_setpoint'
      OR split_part(openfdd_key, '.', 2) IN (
        'sat_sp', 'dsp_sp', 'zone_t_sp', 'chw_supply_sp', 'hw_supply_sp'
      )
    )
)
SELECT equipment_id, role, ts, val AS setpoint
FROM ranked
WHERE rn = 1
ORDER BY equipment_id, role
LIMIT 2000;
```

## diurnal

`sql/analytics/postgres/queries/diurnal_hourly.sql`.

```sql
-- Soft-OPEN analytics pack: hourly mean by role (diurnal shape Soft-OPEN).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  extract(hour FROM ts AT TIME ZONE 'UTC')::int AS hour_utc,
  avg(val) AS avg_val,
  count(*)::bigint AS n
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND split_part(openfdd_key, '.', 2) IN (
    'oa_t', 'web_oa_t', 'sat', 'mat', 'rat', 'zone_t',
    'fan_cmd', 'clg_valve_pct', 'htg_valve_pct'
  )
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
LIMIT 5000;
```

## topology

`sql/analytics/postgres/queries/topology_equipment.sql`.

```sql
-- Soft-OPEN analytics pack: equipment inventory + parent edges (topology Soft-OPEN).
-- Parameter: $1 = building_id / site_id. Soft-OPEN ≠ FQ.
SELECT
  e.equipment_id,
  e.equip_type,
  e.parent_equipment_id,
  (
    SELECT count(DISTINCT split_part(s.openfdd_key, '.', 2))
    FROM sample s
    WHERE s.site_id = $1
      AND split_part(s.openfdd_key, '.', 1) = e.equipment_id
  )::bigint AS role_count,
  (
    SELECT max(s.ts)
    FROM sample s
    WHERE s.site_id = $1
      AND split_part(s.openfdd_key, '.', 1) = e.equipment_id
  ) AS last_sample_ts
FROM equipment e
WHERE e.building_id = $1
ORDER BY e.equip_type NULLS LAST, e.equipment_id
LIMIT 2000;
```

## metering

`sql/analytics/postgres/queries/metering_kwh.sql`.

```sql
-- Soft-OPEN analytics pack: basic energy / interval aggregates by meter role.
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ. Full interval math Soft-OPEN later.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  date_trunc('day', ts) AS day_utc,
  count(*)::bigint AS n,
  min(val) AS min_val,
  max(val) AS max_val,
  avg(val) AS avg_val,
  (max(val) - min(val)) AS delta_val
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND (
    split_part(openfdd_key, '.', 2) LIKE '%kwh%'
    OR split_part(openfdd_key, '.', 2) LIKE '%_kwh'
    OR split_part(openfdd_key, '.', 2) IN (
      'electric_kwh', 'gas_therm', 'steam_mlb', 'water_gal', 'power_kw'
    )
  )
GROUP BY 1, 2, 3
ORDER BY 3 DESC, 1, 2
LIMIT 2000;
```

## pid-hunting

`sql/analytics/postgres/queries/pid_hunting_proxy.sql`.

The threshold is role-dependent after metric-c-v2 normalization: temperature
roles (`sat`, `zone_t`) use a sample standard deviation greater than
`4.444444444444445 °C`; duct static pressure (`dsp`) uses greater than
`1990.72 Pa`; percent-command roles retain the unitless numeric cutoff `8`.
The SQL applies the role-specific equivalent so source-declared units do not
change which historical samples cross the threshold. This is a hunting proxy,
not the full PID-HUNT diagnostic.

```sql
-- Soft-OPEN analytics pack: hunting proxy via role stddev (not full PID-HUNT suite).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  avg(val) AS avg_val,
  stddev_samp(val) AS stddev_val,
  CASE
    WHEN count(*) >= 24 AND stddev_samp(val) IS NOT NULL AND stddev_samp(val) > 8.0
      THEN 'HUNT_PROXY'
    ELSE 'OK'
  END AS hunt_flag
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND split_part(openfdd_key, '.', 2) IN (
    'clg_valve_pct', 'htg_valve_pct', 'oa_damper_pct', 'fan_cmd',
    'dsp', 'sat', 'zone_t'
  )
GROUP BY 1, 2
HAVING count(*) >= 12
ORDER BY stddev_val DESC NULLS LAST
LIMIT 2000;
```

## sql-anomaly

`sql/analytics/postgres/queries/sql_anomaly_zscore.sql` with coverage from `sql_anomaly_series.sql`.

The product response is one row per flagged timestamp (`query_version: sql-anomaly-event-v1`). The baseline is the previous `$5` samples for that equipment and role. The current sample is excluded from its own mean and sample standard deviation. A scored sample is an event when `|z| >= $6`. `$7` false keeps every flagged timestamp. `$7` true keeps rising edges only. `coverage.n_flagged` still counts flagged samples the edge filter omits.

| Bind | Meaning |
|------|---------|
| `$1` | `site_id` |
| `$2` | window start (`timestamptz`, NULL = open) |
| `$3` | window end (`timestamptz`, NULL = open, half-open) |
| `$4` | equipment ids (`text[]`, NULL/empty = all). Exact `= ANY ($4)` match |
| `$5` | `window_rows` (int, prior-sample count) |
| `$6` | `z_threshold` (double precision) |
| `$7` | `transition_events` (boolean) |

Screened roles: `sat`, `mat`, `rat`, `oa_t`, `web_oa_t`, `zone_t`, `dsp`. The event query returns at most 2000 rows ordered by `|z|` descending, then timestamp descending. The counts row is always present, including when no timestamp is flagged. Short, constant, and all-null series are classified by `sql_anomaly_series.sql` and do not become a zero-filled summary.

## mv-change-point

`sql/analytics/postgres/queries/mv_change_point_daily.sql`.

For temperature roles, the legacy 25% test was relative to a 0 °F origin and
had a 1 °F minimum delta. Its metric-c-v2 equivalent uses the SI origin
`−17.77777777777778 °C` and minimum delta `0.5555555555555556 °C`:
`abs(delta_C) >= greatest(abs(prev_C − (−17.77777777777778)) * 0.25,
0.5555555555555556)`. This deliberately preserves the legacy predicate rather
than making 0 °C the new reference. Non-temperature scalar roles retain their
existing relative/minimum comparison. The pack remains Soft-OPEN and this
description does not qualify the rule.

```sql
-- Soft-OPEN analytics pack: day-over-day mean change (change-point Soft-OPEN).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ (not full MV suite).
WITH daily AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    date_trunc('day', ts) AS day_utc,
    avg(val) AS avg_val,
    count(*)::bigint AS n
  FROM sample
  WHERE site_id = $1
    AND val IS NOT NULL
    AND split_part(openfdd_key, '.', 2) IN (
      'electric_kwh', 'gas_therm', 'power_kw', 'steam_mlb',
      'oa_t', 'web_oa_t', 'sat', 'zone_t'
    )
  GROUP BY 1, 2, 3
  HAVING count(*) >= 6
),
ranked AS (
  SELECT
    equipment_id,
    role,
    openfdd_key,
    day_utc,
    avg_val,
    n,
    lag(avg_val) OVER (
      PARTITION BY openfdd_key ORDER BY day_utc
    ) AS prev_avg
  FROM daily
),
thresholded AS (
  SELECT
    *,
    CASE
      WHEN role IN ('oa_t', 'web_oa_t', 'sat', 'zone_t')
        THEN greatest(abs(prev_avg - (-17.77777777777778)) * 0.25, 0.5555555555555556)
      ELSE greatest(abs(prev_avg) * 0.25, 1.0)
    END AS required_delta
  FROM ranked
)
SELECT
  equipment_id,
  role,
  day_utc,
  avg_val,
  prev_avg,
  (avg_val - prev_avg) AS delta_avg,
  n,
  CASE
    WHEN prev_avg IS NULL THEN 'FIRST'
    WHEN abs(avg_val - prev_avg) >= required_delta
      THEN 'CHANGE'
    ELSE 'STABLE'
  END AS change_flag
FROM thresholded
WHERE prev_avg IS NOT NULL
  AND abs(avg_val - prev_avg) >= required_delta
ORDER BY day_utc DESC, abs(avg_val - prev_avg) DESC
LIMIT 2000;
```

## fuel

`sql/analytics/postgres/queries/fuel_daily.sql`.

```sql
-- Soft-OPEN analytics pack: daily fuel / utility aggregates by role.
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ (campus fuel import path stays separate).
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  date_trunc('day', ts) AS day_utc,
  count(*)::bigint AS n,
  min(val) AS min_val,
  max(val) AS max_val,
  avg(val) AS avg_val,
  (max(val) - min(val)) AS delta_val
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND (
    split_part(openfdd_key, '.', 2) LIKE '%gas%'
    OR split_part(openfdd_key, '.', 2) LIKE '%fuel%'
    OR split_part(openfdd_key, '.', 2) LIKE '%therm%'
    OR split_part(openfdd_key, '.', 2) IN (
      'gas_therm', 'gas_ccf', 'fuel_gal', 'steam_mlb', 'electric_kwh', 'power_kw'
    )
  )
GROUP BY 1, 2, 3
ORDER BY 3 DESC, 1, 2
LIMIT 2000;
```

## rcx-preset-coverage

`sql/analytics/postgres/queries/rcx_preset_role_coverage.sql`.

```sql
-- Soft-OPEN analytics pack: role coverage inventory for RCx preset eligibility Soft-OPEN.
-- Parameter: $1 = site_id. Preset catalog stays in Rust; this feeds coverage only.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  min(ts) AS first_ts,
  max(ts) AS last_ts
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND split_part(openfdd_key, '.', 2) IN (
    'oa_t', 'web_oa_t', 'sat', 'mat', 'rat', 'oa_damper_pct',
    'zone_t', 'dsp', 'chw_supply_t', 'hw_supply_t',
    'fan_cmd', 'clg_valve_pct', 'htg_valve_pct'
  )
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 5000;
```
