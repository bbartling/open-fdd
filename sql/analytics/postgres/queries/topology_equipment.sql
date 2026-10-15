-- Soft-OPEN analytics pack: equipment inventory + parent edges (topology Soft-OPEN).
-- Parameters:
--   $1 = building_id / site_id
--   $2 = window start (timestamptz, NULL = open) — scopes sample subqueries
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Soft-OPEN ≠ FQ.
SELECT
  e.equipment_id,
  e.equip_type,
  e.parent_equipment_id,
  (
    SELECT count(DISTINCT split_part(s.openfdd_key, '.', 2))
    FROM sample s
    WHERE s.site_id = $1
      AND split_part(s.openfdd_key, '.', 1) = e.equipment_id
      AND ($2::timestamptz IS NULL OR s.ts >= $2)
      AND ($3::timestamptz IS NULL OR s.ts < $3)
  )::bigint AS role_count,
  (
    SELECT max(s.ts)
    FROM sample s
    WHERE s.site_id = $1
      AND split_part(s.openfdd_key, '.', 1) = e.equipment_id
      AND ($2::timestamptz IS NULL OR s.ts >= $2)
      AND ($3::timestamptz IS NULL OR s.ts < $3)
  ) AS last_sample_ts
FROM equipment e
WHERE e.building_id = $1
  AND (
    $4::text[] IS NULL
    OR cardinality($4) = 0
    OR e.equipment_id = ANY ($4)
  )
ORDER BY e.equip_type NULLS LAST, e.equipment_id
LIMIT 2000;
