-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_monthly_fault.sql — BAS monthly kWh vs utility monthly bills (% deviation)
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
bas_monthly AS (
  SELECT
    to_char(timestamp_utc AT TIME ZONE 'UTC', 'YYYY-MM') AS billing_period,
    SUM(
      COALESCE(
        CAST(kwh AS DOUBLE PRECISION),
        CASE
          WHEN dt_seconds > 0.0 AND dt_seconds <= ({{MAX_GAP_HOURS}} * 3600.0)
          THEN CAST(electric_kw AS DOUBLE PRECISION) * dt_seconds / 3600.0
          ELSE 0.0
        END,
        0.0
      )
    ) AS bas_kwh
  FROM bas_raw
  GROUP BY 1
),
util AS (
  SELECT
    billing_period,
    CAST(kwh AS DOUBLE PRECISION) AS util_kwh
  FROM utility_monthly
  WHERE kwh IS NOT NULL
),
joined AS (
  SELECT
    u.billing_period,
    u.util_kwh,
    COALESCE(b.bas_kwh, 0.0) AS bas_kwh,
    CASE
      WHEN u.util_kwh IS NULL OR u.util_kwh <= 0 THEN 0
      WHEN ABS(COALESCE(b.bas_kwh, 0.0) - u.util_kwh) / u.util_kwh * 100.0 > {{UTIL_PCT_ERR}}
      THEN 1
      ELSE 0
    END AS raw_fault
  FROM util u
  LEFT JOIN bas_monthly b ON b.billing_period = u.billing_period
)
SELECT
  '__UTIL_MONTHLY__' AS equipment_id,
  CAST(SUM(raw_fault) AS DOUBLE PRECISION) * 720.0 AS fault_hours,
  NULL::double precision AS covered_hours,
  NULL::double precision AS fault_pct
FROM joined;
