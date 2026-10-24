-- Sensor staleness / range flags. One row per bound key.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
WITH role_stats AS (
  SELECT
    a.equipment_id,
    a.role,
    a.openfdd_key,
    count(*)::bigint AS n,
    max(s.ts) AS last_ts,
    min(s.val) AS min_val,
    max(s.val) AS max_val,
    stddev_samp(s.val) AS stddev_val
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
  GROUP BY a.equipment_id, a.role, a.openfdd_key
)
SELECT
  equipment_id,
  role,
  openfdd_key,
  n,
  last_ts,
  min_val,
  max_val,
  stddev_val,
  CASE
    WHEN last_ts < now() - interval '24 hours' THEN 'STALE'
    WHEN stddev_val IS NOT NULL AND stddev_val = 0 AND n >= 12 THEN 'FLATLINE'
    WHEN min_val IS NOT NULL AND max_val IS NOT NULL
         AND (min_val < -40 OR max_val > 250)
         AND role LIKE '%_t' THEN 'RANGE'
    ELSE 'OK'
  END AS fault_flag
FROM role_stats
ORDER BY
  CASE
    WHEN last_ts < now() - interval '24 hours' THEN 0
    WHEN stddev_val IS NOT NULL AND stddev_val = 0 AND n >= 12 THEN 1
    WHEN min_val IS NOT NULL AND max_val IS NOT NULL
         AND (min_val < -40 OR max_val > 250)
         AND role LIKE '%_t' THEN 2
    ELSE 3
  END,
  equipment_id,
  role,
  openfdd_key
LIMIT 2000;
