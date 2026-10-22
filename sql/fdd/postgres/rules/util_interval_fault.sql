-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_interval_fault.sql — BAS 15m vs utility interval (rolling MAE proxy)
WITH bas_raw AS (
  SELECT
    timestamp_utc,
    kwh,
    electric_kw,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) - timestamp_utc
    )) AS dt_seconds
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
),
bas AS (
  SELECT
    timestamp_utc,
    COALESCE(
      CAST(kwh AS DOUBLE PRECISION),
      CASE
        WHEN dt_seconds > 0.0 AND dt_seconds <= ({{MAX_GAP_HOURS}} * 3600.0)
        THEN CAST(electric_kw AS DOUBLE PRECISION) * dt_seconds / 3600.0
        ELSE 0.0
      END
    ) AS bas_kwh
  FROM bas_raw
),
util AS (
  SELECT
    timestamp_utc,
    CAST(kwh AS DOUBLE PRECISION) AS util_kwh
  FROM utility_interval
  WHERE kwh IS NOT NULL
),
joined AS (
  SELECT
    b.timestamp_utc,
    ABS(COALESCE(b.bas_kwh, 0.0) - COALESCE(u.util_kwh, 0.0)) AS abs_err
  FROM bas b
  INNER JOIN util u ON b.timestamp_utc = u.timestamp_utc
),
agg AS (
  SELECT
  AVG(abs_err) AS mae
  FROM joined
)
SELECT
  '__UTIL_INTERVAL__' AS equipment_id,
  CASE
    WHEN (SELECT COUNT(*) FROM util) = 0 THEN 0.0
    WHEN mae > {{UTIL_INTERVAL_MAE}} THEN 720.0
    ELSE 0.0
  END AS fault_hours,
  NULL::double precision AS covered_hours,
  NULL::double precision AS fault_pct
FROM agg;
