SELECT point_id, point_name, value, units, ts AS timestamp_utc
FROM history
WHERE ts >= :start_ts
  AND ts <= :end_ts
  AND site_id = :site_id
ORDER BY ts ASC
LIMIT :limit
