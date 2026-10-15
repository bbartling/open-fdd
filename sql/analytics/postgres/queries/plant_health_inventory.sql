-- Soft-OPEN analytics pack: plant health inventory (score unavailable until cohort SQL).
-- Parameters:
--   $1 = building_id
--   $2 = equipment_ids (text[], NULL/empty = all)
-- Window binds are honestly unsupported: inventory is equipment-table scoped
-- (no sample ts). Soft-OPEN ≠ FQ.
SELECT equipment_id, equip_type
FROM equipment
WHERE building_id = $1
  AND (
    $2::text[] IS NULL
    OR cardinality($2) = 0
    OR equipment_id = ANY ($2)
  )
ORDER BY equip_type NULLS LAST, equipment_id
LIMIT 500;
