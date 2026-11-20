-- Reset scatters: each sample of a supply / leaving temperature paired with outdoor air (issue #1757, the RCx SAT, HW,
-- CHW and CW reset scatters). Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, no
-- extensions). Rendered by open_fdd.analytics.sql_reset_scatter.render_reset_scatter_sql with an inline table:
--   {pairs}  scatter_id, equipment_id, y_key, x_key, max_age_ms: one scatter per row (an equipment can have several,
--            e.g. SAT and HW supply), y the plotted point, x the outdoor-air point (web dry bulb, wet bulb or BAS OAT),
--            and the as-of age limit for x (milliseconds).
-- {ts_ms} is the engine's ts-to-epoch-ms expression; all time math is integer milliseconds.
--
-- Same pairing as bas_vs_web_points.sql and open_fdd.analytics.weather_resolver.bas_vs_web_pairs: each y sample with the
-- latest x reading at or before it, at most max_age_ms old (an x reading sorts before a y sample at the same time); an
-- unpaired y sample is left out. x readings up to max_age_ms before the window start still pair.
-- Columns: scatter_id, equipment_id, t (epoch ms), x, y. Ordered by scatter_id, t.
WITH pairs AS (
{pairs}
),
ys AS (
  SELECT p.scatter_id, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN pairs p ON p.y_key = s.point_key
  WHERE s.site_id = {site_id}
),
xs AS (
  SELECT p.scatter_id, p.max_age_ms, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN pairs p ON p.x_key = s.point_key
  WHERE s.site_id = {site_id}
),
stream AS (
  SELECT scatter_id, t, 2 AS src, value AS y, CAST(NULL AS DOUBLE PRECISION) AS x
  FROM ys
  WHERE 1 = 1{window_filter}
  UNION ALL
  SELECT w.scatter_id, w.t, 1, NULL, w.value
  FROM xs w
  WHERE 1 = 1{x_window_filter}
),
grouped AS (
  SELECT scatter_id, t, src, y, x,
         COUNT(x) OVER (PARTITION BY scatter_id ORDER BY t, src ROWS UNBOUNDED PRECEDING) AS grp
  FROM stream
),
carried AS (
  SELECT scatter_id, t, src, y,
         MAX(x) OVER (PARTITION BY scatter_id, grp) AS x,
         MAX(CASE WHEN src = 1 THEN t END) OVER (PARTITION BY scatter_id, grp) AS x_t
  FROM grouped
)
SELECT c.scatter_id, p.equipment_id, c.t, c.x, c.y
FROM carried c
JOIN pairs p ON p.scatter_id = c.scatter_id
WHERE c.src = 2 AND c.x IS NOT NULL AND c.t - c.x_t <= p.max_age_ms
ORDER BY c.scatter_id, c.t
