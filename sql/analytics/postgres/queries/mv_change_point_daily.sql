-- Soft-OPEN analytics pack: day-over-day mean change (change-point Soft-OPEN).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ (not full MV suite).
WITH daily AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    date_trunc('day', ts) AS day_utc,
    avg(val) AS avg_val,
    count(*)::bigint AS n
  FROM sample
  WHERE site_id = $1
    AND val IS NOT NULL
    AND split_part(openfdd_key, '.', 2) IN (
      'electric_kwh', 'gas_therm', 'power_kw', 'steam_mlb',
      'oa_t', 'web_oa_t', 'sat', 'zone_t'
    )
  GROUP BY 1, 2, 3
  HAVING count(*) >= 6
),
ranked AS (
  SELECT
    equipment_id,
    role,
    day_utc,
    avg_val,
    n,
    lag(avg_val) OVER (
      PARTITION BY equipment_id, role ORDER BY day_utc
    ) AS prev_avg
  FROM daily
)
SELECT
  equipment_id,
  role,
  day_utc,
  avg_val,
  prev_avg,
  (avg_val - prev_avg) AS delta_avg,
  n,
  CASE
    WHEN prev_avg IS NULL THEN 'FIRST'
    WHEN abs(avg_val - prev_avg) >= greatest(abs(prev_avg) * 0.25, 1.0)
      THEN 'CHANGE'
    ELSE 'STABLE'
  END AS change_flag
FROM ranked
WHERE prev_avg IS NOT NULL
  AND abs(avg_val - prev_avg) >= greatest(abs(prev_avg) * 0.25, 1.0)
ORDER BY day_utc DESC, abs(avg_val - prev_avg) DESC
LIMIT 2000;
