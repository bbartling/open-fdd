-- GENERATED COPY of sql/analytics/economizer_metrics.sql by scripts/nf/sync_shared.py: edit the source, then re-run the script.
-- Economizer free-cooling metrics per air handler over the core sample view fdd.input_sample (issue #1649).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, no extensions).
-- Rendered by open_fdd.analytics.sql_economizer.render_economizer_sql. Python binds the roles per equipment from bound
-- roles (never point names) and substitutes them as an inline table:
--   {roles}  equipment_id, role, point_key with role in fan | oat | rat | mat | damper. Every 'fan' point is OR'ed
--            (fan status and fan command); oat is the one outdoor-air point pandas resolves (BAS before web unless
--            prefer_web_oat); damper is the outside-air damper.
-- {ts_ms} is the engine's ts-to-epoch-ms expression; all time math is integer milliseconds.
--
-- Same semantics as the metrics of open_fdd.analytics.core.economizer_free_cooling_diagnostics:
--   * the grid is every sample time of the equipment's points. Values join at the exact grid time: the inputs are
--     expected on a common grid (the hooks align history on one before analysis), as pandas' wide frame is;
--   * fan on at a grid time: any fan point's value, scaled to 0-1 (a value above 1.5 is a percent), is above 0.05;
--   * fan_on_ms: forward intervals over the grid (the last time owns 0; an interval over {max_gap_ms} is unknown, 0)
--     while the fan is on; n_fan_on counts fan-on grid times;
--   * identifiable: fan on, OAT and RAT present, and |OAT - RAT| >= {dt_min} (delta degC); MAT is not needed;
--   * the damper fraction follows pandas norm_command(auto) per series: the whole damper series is percent when any
--     value in the window is above 1, else it is already 0-1;
--   * MAT residual on identifiable rows with MAT and a damper value: MAT - (RAT + damper * (OAT - RAT)); the median uses the
--     middle row (or the mean of the two middle rows), and the MAE is the mean absolute residual.
-- The archived 4.x query (sql/analytics/postgres/queries/economizer_deltas.sql at tag v4.0.11-central) returned the
-- per-sample deltas with fan_status only; this port returns the per-equipment metrics with the pandas fan rule.
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
),
timed AS (
  SELECT equipment_id, t, fan_on, oat, rat, mat, damper,
         LEAD(t) OVER (PARTITION BY equipment_id ORDER BY t) - t AS dt_ms
  FROM grid
),
scored AS (
  SELECT equipment_id, fan_on,
         CASE WHEN fan_on = 1 AND dt_ms > 0 AND dt_ms <= {max_gap_ms} THEN dt_ms ELSE 0 END AS on_ms,
         CASE WHEN fan_on = 1 AND oat IS NOT NULL AND rat IS NOT NULL
                   AND ABS(oat - rat) >= {dt_min} THEN 1 ELSE 0 END AS ident,
         CASE WHEN fan_on = 1 AND oat IS NOT NULL AND rat IS NOT NULL AND mat IS NOT NULL
                   AND ABS(oat - rat) >= {dt_min} AND damper IS NOT NULL
              THEN mat - (rat + damper * (oat - rat)) END AS resid
  FROM timed
),
ranked AS (
  SELECT equipment_id, resid,
         ROW_NUMBER() OVER (PARTITION BY equipment_id ORDER BY resid) AS rn,
         COUNT(*) OVER (PARTITION BY equipment_id) AS n
  FROM scored
  WHERE resid IS NOT NULL
),
med AS (
  SELECT equipment_id, AVG(resid) AS median_resid
  FROM ranked
  WHERE 2 * rn IN (n, n + 1, n + 2)
  GROUP BY equipment_id
),
totals AS (
  SELECT equipment_id,
         SUM(on_ms) AS fan_on_ms,
         SUM(fan_on) AS n_fan_on,
         SUM(ident) AS n_identifiable,
         COUNT(resid) AS n_resid,
         AVG(ABS(resid)) AS mae_resid
  FROM scored
  GROUP BY equipment_id
)
SELECT tt.equipment_id, tt.fan_on_ms, tt.n_fan_on, tt.n_identifiable, tt.n_resid, m.median_resid, tt.mae_resid
FROM totals tt
LEFT JOIN med m ON m.equipment_id = tt.equipment_id
WHERE tt.n_fan_on > 0
ORDER BY tt.equipment_id
