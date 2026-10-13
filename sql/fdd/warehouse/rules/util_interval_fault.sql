-- Generic warehouse template: implement the documented dialect hooks. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_interval_fault.sql — BAS 15m vs utility interval (rolling MAE proxy)
WITH bas AS (
  SELECT
    timestamp_utc,
    COALESCE(
      CAST(kwh AS FLOAT(53)),
      CAST(electric_kw AS FLOAT(53)) * {{POLL_SECONDS}} / 3600.0
    ) AS bas_kwh
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
),
util AS (
  SELECT
    timestamp_utc,
    CAST(kwh AS FLOAT(53)) AS util_kwh
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
  END AS fault_hours
FROM agg;
