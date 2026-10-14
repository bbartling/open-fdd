-- Soft-OPEN analytics pack: plant health inventory (score unavailable until cohort SQL).
-- Parameter: $1 = building_id.
SELECT equipment_id, equip_type
FROM equipment
WHERE building_id = $1
ORDER BY equip_type NULLS LAST, equipment_id
LIMIT 500;
