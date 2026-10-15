-- Soft-OPEN analytics pack: equipment inventory + parent edges (topology Soft-OPEN).
-- Parameter: $1 = building_id / site_id. Soft-OPEN ≠ FQ.
SELECT
  e.equipment_id,
  e.equip_type,
  e.parent_equipment_id,
  (
    SELECT count(DISTINCT split_part(s.openfdd_key, '.', 2))
    FROM sample s
    WHERE s.site_id = $1
      AND split_part(s.openfdd_key, '.', 1) = e.equipment_id
  )::bigint AS role_count,
  (
    SELECT max(s.ts)
    FROM sample s
    WHERE s.site_id = $1
      AND split_part(s.openfdd_key, '.', 1) = e.equipment_id
  ) AS last_sample_ts
FROM equipment e
WHERE e.building_id = $1
ORDER BY e.equip_type NULLS LAST, e.equipment_id
LIMIT 2000;
