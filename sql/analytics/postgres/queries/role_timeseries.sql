-- Soft-OPEN analytics pack: bounded role timeseries (RCx vav/chiller/boiler).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
--   $5 = role suffix pattern (e.g. '%.zone_t')
--   $6 = limit
SELECT ts, openfdd_key, val,
       split_part(openfdd_key, '.', 1) AS equipment_id
FROM sample
WHERE site_id = $1
  AND ($2::timestamptz IS NULL OR ts >= $2)
  AND ($3::timestamptz IS NULL OR ts < $3)
  AND (
    $4::text[] IS NULL
    OR cardinality($4) = 0
    OR split_part(openfdd_key, '.', 1) = ANY ($4)
  )
  AND openfdd_key LIKE $5
ORDER BY ts DESC
LIMIT $6;
