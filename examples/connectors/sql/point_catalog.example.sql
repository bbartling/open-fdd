SELECT point_id, point_name, units, equipment_id
FROM point_catalog
WHERE site_id = :site_id
LIMIT :limit
