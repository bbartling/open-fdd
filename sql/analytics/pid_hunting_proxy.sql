-- Control-loop hunting proxy: per-point spread over fdd.input_sample (issue #1757, archived 4.x `pid-hunting`).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite (no STDDEV / SQRT, no extensions). Rendered by
-- open_fdd.analytics.sql_point_stats.render_pid_hunting_sql. A coarse screen, not the PID-HUNT-1 rule.
--
-- Same rows as open_fdd.analytics.point_stats.pid_hunting_proxy. Roles: clg_valve_pct, htg_valve_pct, oa_damper_pct,
-- fan_cmd (commands as the input contract stores them: 0-1 fractions; no per-value scale guessing, which split a
-- series near 1.5 % across two scales), duct_static (Pa), sat and zone_t (degC). Normalize a percent source to 0-1 at
-- ingest. Per point with at least 12 samples: n, avg_val, var_val (sample variance) and
-- is_hunting = n >= 24 AND stddev above the legacy limit: 4.444 delta degC (8 delta degF) for sat / zone_t, 1990.72 Pa
-- (8 inH2O) for duct_static, 0.08 (8 %) for the commands. Compared as variance > limit^2. Ordered by spread, largest
-- first.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}
    AND p.role IN ('clg_valve_pct', 'htg_valve_pct', 'oa_damper_pct', 'fan_cmd', 'duct_static', 'sat', 'zone_t')
),
win AS (
  SELECT point_key, equipment_id, role, value FROM src WHERE 1 = 1{window_filter}
),
mean AS (
  SELECT point_key, COUNT(*) AS n, AVG(value) AS avg_val FROM win GROUP BY point_key
),
stats AS (
  SELECT w.point_key, w.equipment_id, w.role, MAX(m.n) AS n, MAX(m.avg_val) AS avg_val,
         SUM((w.value - m.avg_val) * (w.value - m.avg_val)) / (MAX(m.n) - 1) AS var_val
  FROM win w JOIN mean m ON m.point_key = w.point_key
  WHERE m.n >= 12
  GROUP BY w.point_key, w.equipment_id, w.role
)
SELECT point_key, equipment_id, role, n, avg_val, var_val,
       CASE WHEN n >= 24 AND var_val > CASE WHEN role IN ('sat', 'zone_t') THEN 19.75308641975309
                                            WHEN role = 'duct_static' THEN 3962966.1184
                                            ELSE 0.0064 END
            THEN 1 ELSE 0 END AS is_hunting
FROM stats
ORDER BY var_val DESC, point_key
