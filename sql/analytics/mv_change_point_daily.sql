-- Day-over-day change in the daily mean per point (issue #1757, archived 4.x `mv-change-point`). A coarse screen; the
-- IPMVP change-point regression is open_fdd.analytics.mv_change_point. Portable SQL: PostgreSQL / TimescaleDB, DuckDB
-- and SQLite (no GREATEST, no extensions). Rendered by open_fdd.analytics.sql_point_stats.render_mv_change_point_sql.
--
-- Same rows as open_fdd.analytics.point_stats.mv_change_points, archived semantics:
--   * a UTC day counts only with at least 6 samples; prev_avg is the previous counted day of the same point;
--   * temperature roles (outdoor_air_intake_temperature, weather_service_air_temperature, discharge_air_temperature, zone_air_temperature) keep the legacy degF predicate on SI data:
--     |delta| >= max(|prev - (-17.778)| * 0.25, 0.5556) (0 degF origin, 1 degF minimum);
--     other roles |delta| >= max(|prev| * 0.25, 1.0);
--   * only CHANGE rows are returned, newest day first, then the larger |delta|, then point_key.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}{role_filter}
),
win AS (
  SELECT point_key, equipment_id, role, value, t - (((t % 86400000) + 86400000) % 86400000) AS day_ms
  FROM src WHERE 1 = 1{window_filter}
),
daily AS (
  SELECT point_key, equipment_id, role, day_ms, AVG(value) AS avg_val, COUNT(*) AS n
  FROM win
  GROUP BY point_key, equipment_id, role, day_ms
  HAVING COUNT(*) >= 6
),
ranked AS (
  SELECT point_key, equipment_id, role, day_ms, avg_val, n,
         LAG(avg_val) OVER (PARTITION BY point_key ORDER BY day_ms) AS prev_avg
  FROM daily
),
thresholded AS (
  SELECT point_key, equipment_id, role, day_ms, avg_val, n, prev_avg,
         ABS(avg_val - prev_avg) AS abs_delta,
         CASE WHEN role IN ('outdoor_air_intake_temperature', 'weather_service_air_temperature', 'discharge_air_temperature', 'zone_air_temperature')
              THEN CASE WHEN ABS(prev_avg - (-17.77777777777778)) * 0.25 > 0.5555555555555556
                        THEN ABS(prev_avg - (-17.77777777777778)) * 0.25 ELSE 0.5555555555555556 END
              ELSE CASE WHEN ABS(prev_avg) * 0.25 > 1.0 THEN ABS(prev_avg) * 0.25 ELSE 1.0 END
         END AS required_delta
  FROM ranked
  WHERE prev_avg IS NOT NULL
)
SELECT point_key, equipment_id, role, day_ms, avg_val, prev_avg, avg_val - prev_avg AS delta_avg, n, required_delta
FROM thresholded
WHERE abs_delta >= required_delta
ORDER BY day_ms DESC, abs_delta DESC, point_key
LIMIT {limit}
