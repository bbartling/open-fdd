-- Daily meter aggregates per point over fdd.input_sample (issue #1757, archived 4.x `metering` and `fuel`: the same
-- query with different role lists). Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite (no extensions).
-- Rendered by open_fdd.analytics.sql_point_stats.render_meter_daily_sql: {role_filter} the meter roles (default
-- open_fdd.analytics.point_stats.METER_ROLES; FUEL_ROLES for the fuel view), listed exactly, never LIKE.
--
-- Same rows as open_fdd.analytics.point_stats.meter_daily: per point and UTC day (day_ms = midnight, epoch ms) of
-- non-NULL samples in the window: n, min_val, max_val, avg_val, delta_val = max - min (for a cumulative register,
-- the day's consumption). Newest day first, then point_key.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}{role_filter}
),
win AS (
  SELECT point_key, equipment_id, role, value, t - (((t % 86400000) + 86400000) % 86400000) AS day_ms
  FROM src WHERE 1 = 1{window_filter}
)
SELECT point_key, equipment_id, role, day_ms, COUNT(*) AS n, MIN(value) AS min_val, MAX(value) AS max_val,
       AVG(value) AS avg_val, MAX(value) - MIN(value) AS delta_val
FROM win
GROUP BY point_key, equipment_id, role, day_ms
ORDER BY day_ms DESC, point_key
LIMIT {limit}
