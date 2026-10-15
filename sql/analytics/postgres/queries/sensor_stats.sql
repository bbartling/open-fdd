-- Soft-OPEN analytics pack: per-equipment/role basic sensor statistics.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Full hunting/staleness Soft-OPEN later.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  min(val) AS min_val,
  max(val) AS max_val,
  avg(val) AS avg_val,
  stddev_samp(val) AS stddev_val,
  min(ts) AS first_ts,
  max(ts) AS last_ts
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
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 2000;
