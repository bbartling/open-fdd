-- Occupancy samples. Equipment and role come from the current binding.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
SELECT s.ts, s.openfdd_key, s.val, a.equipment_id
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
  AND a.role = 'occ_mode'
ORDER BY s.ts DESC, s.openfdd_key
LIMIT 2000;
