-- Soft-OPEN analytics pack: hourly mean by role (diurnal shape Soft-OPEN).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Soft-OPEN ≠ FQ.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  extract(hour FROM ts AT TIME ZONE 'UTC')::int AS hour_utc,
  avg(val) AS avg_val,
  count(*)::bigint AS n
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
  AND split_part(openfdd_key, '.', 2) IN (
    'oa_t', 'web_oa_t', 'sat', 'mat', 'rat', 'zone_t',
    'fan_cmd', 'clg_valve_pct', 'htg_valve_pct'
  )
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
LIMIT 5000;
