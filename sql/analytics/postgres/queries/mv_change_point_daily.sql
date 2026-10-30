-- Day-over-day mean change. The window is one bound key.
-- Temperature roles preserve the historical IP predicate after SI storage:
-- abs(delta_C) >= max(abs(prev_C - 0°F-in-°C) * .25, 1°F-in-°C).
-- Other scalar roles retain their native legacy quarter-scale / 1.0 predicate.
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
),
thresholded AS (
  SELECT
    *,
    CASE
      WHEN role IN ('oa_t', 'web_oa_t', 'sat', 'zone_t')
        THEN greatest(abs(prev_avg - (-17.77777777777778)) * 0.25, 0.5555555555555556)
      ELSE greatest(abs(prev_avg) * 0.25, 1.0)
    END AS required_delta
  FROM ranked
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
    WHEN abs(avg_val - prev_avg) >= required_delta
      THEN 'CHANGE'
    ELSE 'STABLE'
  END AS change_flag
FROM thresholded
WHERE prev_avg IS NOT NULL
  AND abs(avg_val - prev_avg) >= required_delta
ORDER BY day_utc DESC, abs(avg_val - prev_avg) DESC, openfdd_key
LIMIT 2000;
