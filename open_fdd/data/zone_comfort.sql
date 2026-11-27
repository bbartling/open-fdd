-- Zone comfort: share of occupied samples inside the comfort band per zone temperature point (issue #1757, the
-- current zone comfort ranking). Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite (no extensions).
-- Rendered by open_fdd.analytics.sql_point_stats.render_zone_comfort_sql: {occupied} an inline table of occupied
-- intervals (start_ms, end_ms; half-open, UTC epoch ms) from the site's occupancy calendar, {lo} / {hi} the band (degC).
--
-- Same rows as open_fdd.analytics.point_stats.zone_comfort: per zone_air_temperature point, n_occ (samples inside any occupied
-- interval; overlapping intervals count a sample once), n_in_band (lo <= value <= hi) and pct_in_band. Points with
-- no occupied samples are not listed. Worst comfort first (lowest pct), then point_key.
WITH occupied AS (
{occupied}
),
src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter} AND p.role = 'zone_air_temperature'
),
occ AS (
  SELECT point_key, equipment_id, role, value
  FROM src
  WHERE EXISTS (SELECT 1 FROM occupied o WHERE src.t >= o.start_ms AND src.t < o.end_ms){window_filter}
),
agg AS (
  SELECT point_key, equipment_id, role, COUNT(*) AS n_occ,
         SUM(CASE WHEN value >= {lo} AND value <= {hi} THEN 1 ELSE 0 END) AS n_in_band
  FROM occ
  GROUP BY point_key, equipment_id, role
)
SELECT point_key, equipment_id, role, n_occ, n_in_band, 100.0 * n_in_band / n_occ AS pct_in_band
FROM agg
ORDER BY pct_in_band, point_key
