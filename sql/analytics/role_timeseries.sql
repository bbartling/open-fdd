-- Bounded samples of the given roles over fdd.input_sample (issue #1757, archived 4.x `role-timeseries`).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite (no extensions). Rendered by
-- open_fdd.analytics.sql_point_stats.render_role_timeseries_sql: {role_filter} the roles, {limit} the row cap.
--
-- Same rows as open_fdd.analytics.point_stats.role_timeseries: newest first, then point_key, then the larger value
-- (a total order, so the cap cuts at the same row on every engine). t = epoch ms.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}{role_filter}
)
SELECT point_key, equipment_id, role, t, value
FROM src
WHERE 1 = 1{window_filter}
ORDER BY t DESC, point_key, value DESC
LIMIT {limit}
