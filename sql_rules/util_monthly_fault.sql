-- util_monthly_fault.sql — BAS monthly kWh vs utility monthly bills (% deviation)
WITH bas_monthly AS (
  SELECT
    CAST(date_trunc('month', CAST(timestamp_utc AS TIMESTAMP)) AS VARCHAR) AS billing_period,
    SUM(
      COALESCE(
        CAST(kwh AS DOUBLE),
        CAST(electric_kw AS DOUBLE) * {{POLL_SECONDS}} / 3600.0,
        0.0
      )
    ) AS bas_kwh
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
  GROUP BY 1
),
util AS (
  SELECT
    billing_period,
    CAST(kwh AS DOUBLE) AS util_kwh
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
  CAST(SUM(raw_fault) AS DOUBLE) * 720.0 AS fault_hours
FROM joined;
