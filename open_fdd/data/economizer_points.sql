-- Economizer free-cooling points per air handler over the core sample view fdd.input_sample (issue #1649).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28. Rendered by
-- open_fdd.analytics.sql_economizer.render_economizer_points_sql with the same {roles} inline table as
-- economizer_metrics.sql (fan | oat | rat | mat | damper), and the same grid, fan rule and series-level damper scale.
--
-- One row per fan-on grid time with OAT and RAT, the points behind the economizer charts and the twin of
-- open_fdd.analytics.core.build_economizer_delta_points (plus the MAT residual of economizer_free_cooling_diagnostics):
--   d_or = OAT - RAT, d_mr = MAT - RAT (NULL without MAT), identifiable = |OAT - RAT| >= {dt_min},
--   damper_pct = damper fraction x 100 (NULL without a damper),
--   mat_resid = MAT - (RAT + damper x (OAT - RAT)) on identifiable rows with MAT and a damper,
--   oa_frac_pct = 100 x (MAT - RAT) / (OAT - RAT) clamped to -20..120 on identifiable rows with MAT (oa_frac_temp_pct).
-- The archived 4.x query (sql/analytics/postgres/queries/economizer_deltas.sql at tag v4.0.11-central) returned the same
-- per-sample deltas with fan_status only; this port uses the pandas fan rule (fan status OR command).
WITH roles AS (
{roles}
),
src AS (
  SELECT r.equipment_id, r.role, s.point_key, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN roles r ON r.point_key = s.point_key
  WHERE s.site_id = {site_id}
),
win AS (
  SELECT equipment_id, role, point_key, t, value FROM src WHERE 1 = 1{window_filter}
),
damper_scale AS (
  SELECT point_key, CASE WHEN MAX(value) > 1.0 THEN 100.0 ELSE 1.0 END AS div
  FROM win
  WHERE role = 'damper'
  GROUP BY point_key
),
grid AS (
  SELECT w.equipment_id, w.t,
         MAX(CASE WHEN w.role = 'fan'
                  THEN CASE WHEN (CASE WHEN w.value > 1.5 THEN w.value / 100.0 ELSE w.value END) > 0.05 THEN 1 ELSE 0 END
                  ELSE 0 END) AS fan_on,
         MAX(CASE WHEN w.role = 'oat' THEN w.value END) AS oat,
         MAX(CASE WHEN w.role = 'rat' THEN w.value END) AS rat,
         MAX(CASE WHEN w.role = 'mat' THEN w.value END) AS mat,
         MAX(CASE WHEN w.role = 'damper' THEN w.value / d.div END) AS damper
  FROM win w
  LEFT JOIN damper_scale d ON d.point_key = w.point_key
  GROUP BY w.equipment_id, w.t
)
SELECT equipment_id, t,
       oat, rat, mat,
       oat - rat AS d_or,
       mat - rat AS d_mr,
       CASE WHEN ABS(oat - rat) >= {dt_min} THEN 1 ELSE 0 END AS identifiable,
       damper * 100.0 AS damper_pct,
       CASE WHEN ABS(oat - rat) >= {dt_min} AND mat IS NOT NULL AND damper IS NOT NULL
            THEN mat - (rat + damper * (oat - rat)) END AS mat_resid,
       CASE WHEN ABS(oat - rat) >= {dt_min} AND mat IS NOT NULL
            THEN CASE WHEN 100.0 * (mat - rat) / (oat - rat) < -20.0 THEN -20.0
                      WHEN 100.0 * (mat - rat) / (oat - rat) > 120.0 THEN 120.0
                      ELSE 100.0 * (mat - rat) / (oat - rat) END END AS oa_frac_pct
FROM grid
WHERE fan_on = 1 AND oat IS NOT NULL AND rat IS NOT NULL
ORDER BY equipment_id, t
