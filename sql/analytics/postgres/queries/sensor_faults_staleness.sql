-- Soft-OPEN analytics pack: sensor staleness / range flags (not full SV suite).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Soft-OPEN ≠ FQ.
WITH role_stats AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    count(*)::bigint AS n,
    max(ts) AS last_ts,
    min(val) AS min_val,
    max(val) AS max_val,
    stddev_samp(val) AS stddev_val
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND val IS NOT NULL
    AND split_part(openfdd_key, '.', 2) <> ''
  GROUP BY 1, 2
)
SELECT
  equipment_id,
  role,
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
  role
LIMIT 2000;
