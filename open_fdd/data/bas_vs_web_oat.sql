-- BAS vs web outdoor-air temperature per equipment over the core sample view fdd.input_sample (issue #1649).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, no extensions).
-- Rendered by open_fdd.analytics.sql_bas_web.render_bas_web_sql with an inline table:
--   {pairs}  equipment_id, bas_key, web_key, max_age_ms: the equipment's BAS outdoor-air point, the site's web
--            outdoor-air point and the as-of age limit (milliseconds).
-- {ts_ms} is the engine's ts-to-epoch-ms expression; all time math is integer milliseconds.
--
-- Same semantics as open_fdd.analytics.weather_resolver.bas_vs_web_oat_stats:
--   * each BAS sample is paired with the latest web reading at or before it, at most max_age_ms old (carried forward
--     with window functions: a web reading sorts before a BAS sample at the same time); an unpaired sample is not
--     assessed;
--   * d = BAS - web (delta degC); n, bias = mean d, mae = mean |d|, max_abs = max |d|, n_within = |d| <= {band}.
-- The window bounds the BAS samples; web readings up to max_age_ms before the window start still pair.
-- The archived 4.x query (sql/analytics/postgres/queries/bas_vs_web_oat.sql at tag v4.0.11-central) returned the
-- pairs with a correlated subquery; this port returns the statistics and stays linear.
WITH pairs AS (
{pairs}
),
bas AS (
  SELECT p.equipment_id, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN pairs p ON p.bas_key = s.point_key
  WHERE s.site_id = {site_id}
),
web AS (
  SELECT p.equipment_id, p.max_age_ms, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN pairs p ON p.web_key = s.point_key
  WHERE s.site_id = {site_id}
),
stream AS (
  SELECT equipment_id, t, 2 AS src, value AS bas, CAST(NULL AS DOUBLE PRECISION) AS web
  FROM bas
  WHERE 1 = 1{window_filter}
  UNION ALL
  SELECT w.equipment_id, w.t, 1, NULL, w.value
  FROM web w
  WHERE 1 = 1{web_window_filter}
),
grouped AS (
  SELECT equipment_id, t, src, bas, web,
         COUNT(web) OVER (PARTITION BY equipment_id ORDER BY t, src ROWS UNBOUNDED PRECEDING) AS grp
  FROM stream
),
carried AS (
  SELECT equipment_id, t, src, bas,
         MAX(web) OVER (PARTITION BY equipment_id, grp) AS web,
         MAX(CASE WHEN src = 1 THEN t END) OVER (PARTITION BY equipment_id, grp) AS web_t
  FROM grouped
),
paired AS (
  SELECT c.equipment_id, c.bas - c.web AS d
  FROM carried c
  JOIN pairs p ON p.equipment_id = c.equipment_id
  WHERE c.src = 2 AND c.web IS NOT NULL AND c.t - c.web_t <= p.max_age_ms
)
SELECT equipment_id,
       COUNT(*) AS n,
       AVG(d) AS bias,
       AVG(ABS(d)) AS mae,
       MAX(ABS(d)) AS max_abs,
       SUM(CASE WHEN ABS(d) <= {band} THEN 1 ELSE 0 END) AS n_within
FROM paired
GROUP BY equipment_id
ORDER BY equipment_id
