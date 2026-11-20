-- Coverage of the series the z-score anomaly screen reads (issue #1757, archived 4.x `sql_anomaly_series`).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite (no STDDEV / SQRT, no extensions). Rendered by
-- open_fdd.analytics.sql_point_stats.render_anomaly_coverage_sql: {role_filter} the roles, {window} the z-score window.
--
-- Same rows as open_fdd.analytics.point_stats.anomaly_coverage. It starts from fdd.point, so a bound point with no
-- samples in the window is listed with n = 0 (the core view holds no NULL values, so there is no NULL count). Per point:
-- n, var_val (sample variance; NULL below two samples), is_short (n < window: the z-score never scores it) and
-- is_constant (n >= 2 and min = max: no spread to score). Short, constant and empty series stay visible.
WITH pts AS (
  SELECT p.point_key, p.equipment_id, p.role
  FROM fdd.point p
  WHERE p.site_id = {site_id}{point_filter_p}{role_filter}
),
src AS (
  SELECT s.point_key, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN pts ON pts.point_key = s.point_key
  WHERE s.site_id = {site_id}
),
win AS (
  SELECT point_key, value FROM src WHERE 1 = 1{window_filter}
),
agg AS (
  SELECT point_key, COUNT(*) AS n, AVG(value) AS avg_val, MIN(value) AS min_val, MAX(value) AS max_val
  FROM win GROUP BY point_key
),
spread AS (
  SELECT w.point_key, SUM((w.value - a.avg_val) * (w.value - a.avg_val)) AS ss
  FROM win w JOIN agg a ON a.point_key = w.point_key
  GROUP BY w.point_key
)
SELECT pts.point_key, pts.equipment_id, pts.role,
       COALESCE(a.n, 0) AS n,
       CASE WHEN a.n > 1 THEN sp.ss / (a.n - 1) END AS var_val,
       CASE WHEN COALESCE(a.n, 0) < {window} THEN 1 ELSE 0 END AS is_short,
       CASE WHEN a.n > 1 AND a.min_val = a.max_val THEN 1 ELSE 0 END AS is_constant
FROM pts
LEFT JOIN agg a ON a.point_key = pts.point_key
LEFT JOIN spread sp ON sp.point_key = pts.point_key
ORDER BY pts.point_key
