-- GENERATED COPY of sql/analytics/motor_weekly_runtime.sql by scripts/nf/sync_shared.py: edit the source, then re-run the script.
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
--   * partial_week is true when the samples in that week span less than 6 days;
--   * {weeks} (equipment_id, week_ms) optionally replaces the UTC Monday weeks of an equipment with the caller's
--     boundaries (e.g. the site's local Mondays as UTC ms): a sample goes to the last boundary at or before it, and
--     samples before the first boundary are not counted. An equipment with no rows keeps UTC Mondays;
--   * {occ} (equipment_id, start_ms, end_ms) gives occupied intervals (end exclusive). With {use_occ} = 1, in_hours is
--     the ON time whose interval starts while occupied (pandas in_hours; after_hours = run_hours - in_hours);
--   * avg_oat_c is the mean outdoor temperature over the week's counted ON intervals. {oats} is an inline table
--     (equipment_id, point_key) of each equipment's outdoor-air point (web before BAS, chosen by the caller); the
--     reading used is the latest one at or before the interval start and at most {max_gap_ms} old, carried forward
--     with window functions. pandas reindexes the OAT to the exact sample time, so the two agree when the OAT is
--     sampled at the motor's sample times.
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
weeks AS (
{weeks}
),
occ AS (
{occ}
),
counted AS (
  SELECT x.equipment_id, x.role, x.family, x.t,
         CASE WHEN EXISTS (SELECT 1 FROM weeks w WHERE w.equipment_id = x.equipment_id)
              THEN (SELECT MAX(w.week_ms) FROM weeks w WHERE w.equipment_id = x.equipment_id AND w.week_ms <= x.t)
              ELSE x.t - ((x.t - 345600000) % 604800000) END AS week_ms,
         CASE WHEN EXISTS (SELECT 1 FROM occ o
                            WHERE o.equipment_id = x.equipment_id AND o.start_ms <= x.t AND x.t < o.end_ms)
              THEN 1 ELSE 0 END AS occ_flag,
         CASE WHEN (CASE WHEN x.value > 1.5 THEN x.value / 100.0 ELSE x.value END) > 0.05
                   AND x.dt_ms > 0 AND x.dt_ms <= {max_gap_ms}
              THEN x.dt_ms ELSE 0 END AS on_ms
  FROM series x
),
oatsrc AS (
{oats}
),
oat_win AS (
  SELECT os.equipment_id, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN oatsrc os ON os.point_key = s.point_key
  WHERE s.site_id = {site_id}
),
stream AS (
  -- motor samples and OAT readings in one time-ordered stream per equipment; a reading sorts before a sample at the
  -- same time, so "at or before" holds
  SELECT equipment_id, role, family, t, week_ms, occ_flag, on_ms, 2 AS src, CAST(NULL AS DOUBLE PRECISION) AS oat
  FROM counted
  WHERE week_ms IS NOT NULL
  UNION ALL
  SELECT equipment_id, NULL, NULL, t, NULL, NULL, NULL, 1, value
  FROM oat_win
  WHERE 1 = 1{window_filter}
),
grouped AS (
  SELECT equipment_id, role, family, t, week_ms, occ_flag, on_ms, src, oat,
         COUNT(oat) OVER (PARTITION BY equipment_id ORDER BY t, src ROWS UNBOUNDED PRECEDING) AS grp
  FROM stream
),
carried AS (
  SELECT equipment_id, role, family, t, week_ms, occ_flag, on_ms, src,
         MAX(oat) OVER (PARTITION BY equipment_id, grp) AS oat,
         MAX(CASE WHEN src = 1 THEN t END) OVER (PARTITION BY equipment_id, grp) AS oat_t
  FROM grouped
)
SELECT equipment_id,
       role AS signal,
       family AS motor_family,
       week_ms AS week_start_ms,
       SUM(on_ms) / 3600000.0 AS run_hours,
       COUNT(*) AS n_samples,
       CASE WHEN MAX(t) - MIN(t) < 518400000 THEN 1 ELSE 0 END AS partial_week,
       AVG(CASE WHEN on_ms > 0 AND oat IS NOT NULL AND t - oat_t <= {max_gap_ms} THEN oat END) AS avg_oat_c,
       CASE WHEN {use_occ} = 1 THEN SUM(CASE WHEN occ_flag = 1 THEN on_ms ELSE 0 END) / 3600000.0 END AS in_hours
FROM carried
WHERE src = 2
GROUP BY equipment_id, role, family, week_ms
HAVING SUM(on_ms) > 0
ORDER BY equipment_id, motor_family, week_start_ms
