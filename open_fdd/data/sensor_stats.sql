-- Per-point sample statistics over the core sample view fdd.input_sample (issue #1757, archived 4.x `sensor-stats`).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.25 (no STDDEV / SQRT, no extensions).
-- Rendered by open_fdd.analytics.sql_point_stats.render_sensor_stats_sql with checked literals.
--
-- Same numbers as open_fdd.analytics.point_stats.sensor_stats, per point of non-NULL samples in the window:
--   n, min_val, max_val, avg_val, var_val (sample variance, n - 1; NULL for one sample; two-pass, centred on the mean),
--   first_ms / last_ms (epoch ms). The runner returns stddev_val = sqrt(var_val). Two points of one role stay
--   separate rows; nothing is summed across points.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}
),
win AS (
  SELECT point_key, equipment_id, role, t, value FROM src WHERE 1 = 1{window_filter}
),
mean AS (
  SELECT point_key, AVG(value) AS avg_val FROM win GROUP BY point_key
)
SELECT w.point_key, w.equipment_id, w.role,
       COUNT(*) AS n,
       MIN(w.value) AS min_val,
       MAX(w.value) AS max_val,
       MAX(m.avg_val) AS avg_val,
       CASE WHEN COUNT(*) > 1
            THEN SUM((w.value - m.avg_val) * (w.value - m.avg_val)) / (COUNT(*) - 1) END AS var_val,
       MIN(w.t) AS first_ms,
       MAX(w.t) AS last_ms
FROM win w
JOIN mean m ON m.point_key = w.point_key
GROUP BY w.point_key, w.equipment_id, w.role
ORDER BY w.point_key
