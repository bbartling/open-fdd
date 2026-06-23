SELECT point_id, point_name, value, units, ts AS timestamp_utc
FROM current_values
WHERE site_id = :site_id
LIMIT :limit
