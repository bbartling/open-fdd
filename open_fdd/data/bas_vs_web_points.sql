-- BAS vs web outdoor-air temperature, one row per paired BAS sample (issue #1649: the NF chart points).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, no extensions).
-- Rendered by open_fdd.analytics.sql_bas_web.render_bas_web_points_sql with the same placeholders as
-- bas_vs_web_oat.sql ({pairs}, {ts_ms}, {site_id}, {window_filter}, {web_window_filter}); the pairing is the same:
-- each BAS sample with the latest web reading at or before it, at most max_age_ms old (pandas merge_asof backward,
-- as open_fdd.analytics.weather_resolver.bas_vs_web_pairs). Columns: equipment_id, t (epoch ms), bas, web, d = bas - web.
-- bas_vs_web_oat.sql aggregates exactly these rows.
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
  SELECT c.equipment_id, c.t, c.bas, c.web, c.bas - c.web AS d
  FROM carried c
  JOIN pairs p ON p.equipment_id = c.equipment_id
  WHERE c.src = 2 AND c.web IS NOT NULL AND c.t - c.web_t <= p.max_age_ms
)
SELECT equipment_id, t, bas, web, d
FROM paired
ORDER BY equipment_id, t
