-- Soft-OPEN analytics pack: daily fuel / utility aggregates by role.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Soft-OPEN ≠ FQ (campus fuel import path stays separate).
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  date_trunc('day', ts) AS day_utc,
  count(*)::bigint AS n,
  min(val) AS min_val,
  max(val) AS max_val,
  avg(val) AS avg_val,
  (max(val) - min(val)) AS delta_val
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
  AND (
    split_part(openfdd_key, '.', 2) LIKE '%gas%'
    OR split_part(openfdd_key, '.', 2) LIKE '%fuel%'
    OR split_part(openfdd_key, '.', 2) LIKE '%therm%'
    OR split_part(openfdd_key, '.', 2) IN (
      'gas_therm', 'gas_ccf', 'fuel_gal', 'steam_mlb', 'electric_kwh', 'power_kw'
    )
  )
GROUP BY 1, 2, 3
ORDER BY 3 DESC, 1, 2
LIMIT 2000;
