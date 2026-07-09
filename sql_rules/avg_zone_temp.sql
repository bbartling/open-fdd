-- avg_zone_temp.sql
SELECT
  equipment_id,
  AVG(zone_t) AS avg_zone_temp,
  MIN(zone_t) AS min_zone_temp,
  MAX(zone_t) AS max_zone_temp
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;
