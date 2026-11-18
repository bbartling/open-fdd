-- Weekly motor run hours over the core sample view fdd.input_sample (issue #1649).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, integer modulo, no extensions).
-- Rendered by open_fdd.analytics.sql_runtime.render_runtime_sql, which substitutes the {placeholders} with checked
-- literals: the quoted site id, an optional equipment filter, the window bounds and the engine's ts-to-epoch-ms
-- expression ({ts_ms}). All time math is in integer milliseconds, so the engines agree to the millisecond.
--
-- Same semantics as open_fdd.analytics.core.motor_run_hours_weekly on each chosen motor point's samples:
--   * motor roles come from bound roles only, never from point names. Families, status before command:
--       fan      fan_status, fan_cmd
--       pump     pump_status, pump_cmd
--       chw_pump chw_pump_status, chw_pump_cmd
--       hw_pump  hw_pump_cmd
--     A family uses its status point when one has samples in the window, else its command point.
--   * a role bound to two points on one equipment is ambiguous: it is left out, never summed;
--   * a sample is ON when its value, scaled to 0-1 (a value above 1.5 is a percent and is divided by 100), is above
--     0.05 (the run-proof threshold);
--   * each sample owns the interval to the point's next sample. An interval longer than {max_gap_ms} is unknown and
--     counts 0 hours (it is not clipped); the last sample owns 0;
--   * the interval is booked to the UTC week (Monday 00:00) of its starting sample; weeks with no ON time are omitted;
--   * partial_week is true when the samples in that week span less than 6 days.
-- 345600000 ms is Monday 1970-01-05 00:00 UTC and 604800000 ms is one week, so t - ((t - 345600000) % 604800000) is
-- the start of t's week (for timestamps after 1970-01-05).
--
-- plant_group (air / boiler / chiller) comes from equipment metadata, not from the samples; the Python wrapper adds it.
-- The archived 4.x query (sql/analytics/postgres/queries/motor_weekly_runtime.sql at tag v4.0.11-central) read the
-- 4.x sample tables and guessed the plant from the equipment type text; this port reads the v5 SI core.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}
    AND p.equipment_id IS NOT NULL
    AND p.role IN ('fan_status', 'fan_cmd', 'pump_status', 'pump_cmd', 'chw_pump_status', 'chw_pump_cmd',
                   'hw_pump_cmd'){equipment_filter}
),
windowed AS (
  SELECT point_key, equipment_id, role, t, value
  FROM src
  WHERE 1 = 1{window_filter}
),
bound AS (
  SELECT equipment_id, role, MIN(point_key) AS point_key
  FROM (SELECT DISTINCT equipment_id, role, point_key FROM windowed) d
  GROUP BY equipment_id, role
  HAVING COUNT(*) = 1
),
tagged AS (
  SELECT equipment_id, role, point_key,
         CASE WHEN role IN ('fan_status', 'fan_cmd') THEN 'fan'
              WHEN role IN ('pump_status', 'pump_cmd') THEN 'pump'
              WHEN role IN ('chw_pump_status', 'chw_pump_cmd') THEN 'chw_pump'
              ELSE 'hw_pump' END AS family,
         CASE WHEN role LIKE '%status' THEN 1 ELSE 2 END AS pref
  FROM bound
),
chosen AS (
  SELECT t.equipment_id, t.role, t.point_key, t.family
  FROM tagged t
  WHERE t.pref = (SELECT MIN(t2.pref) FROM tagged t2
                  WHERE t2.equipment_id = t.equipment_id AND t2.family = t.family)
),
series AS (
  SELECT c.equipment_id, c.role, c.family, w.t, w.value,
         LEAD(w.t) OVER (PARTITION BY c.point_key ORDER BY w.t) - w.t AS dt_ms
  FROM chosen c
  JOIN windowed w ON w.point_key = c.point_key
),
counted AS (
  SELECT equipment_id, role, family, t,
         t - ((t - 345600000) % 604800000) AS week_ms,
         CASE WHEN (CASE WHEN value > 1.5 THEN value / 100.0 ELSE value END) > 0.05
                   AND dt_ms > 0 AND dt_ms <= {max_gap_ms}
              THEN dt_ms ELSE 0 END AS on_ms
  FROM series
)
SELECT equipment_id,
       role AS signal,
       family AS motor_family,
       week_ms AS week_start_ms,
       SUM(on_ms) / 3600000.0 AS run_hours,
       COUNT(*) AS n_samples,
       CASE WHEN MAX(t) - MIN(t) < 518400000 THEN 1 ELSE 0 END AS partial_week
FROM counted
GROUP BY equipment_id, role, family, week_ms
HAVING SUM(on_ms) > 0
ORDER BY equipment_id, motor_family, week_start_ms
