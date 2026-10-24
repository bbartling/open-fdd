-- Day-over-day mean change. The window is one bound key.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
WITH daily AS (
  SELECT
    a.equipment_id,
    a.role,
    a.openfdd_key,
    date_trunc('day', s.ts) AS day_utc,
    avg(s.val) AS avg_val,
    count(*)::bigint AS n
  FROM sample s
  JOIN authorized_series a
    ON a.site_id = s.site_id
   AND a.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND ($2::timestamptz IS NULL OR s.ts >= $2)
    AND ($3::timestamptz IS NULL OR s.ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR a.equipment_id = ANY ($4)
    )
    AND s.val IS NOT NULL
    AND a.role IN (
      'electric_kwh', 'gas_therm', 'power_kw', 'steam_mlb',
      'oa_t', 'web_oa_t', 'sat', 'zone_t'
    )
  GROUP BY a.equipment_id, a.role, a.openfdd_key, 4
  HAVING count(*) >= 6
),
ranked AS (
  SELECT
    equipment_id,
    role,
    openfdd_key,
    day_utc,
    avg_val,
    n,
    lag(avg_val) OVER (
      PARTITION BY openfdd_key ORDER BY day_utc
    ) AS prev_avg
  FROM daily
)
SELECT
  equipment_id,
  role,
  openfdd_key,
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
ORDER BY day_utc DESC, abs(avg_val - prev_avg) DESC, openfdd_key
LIMIT 2000;
