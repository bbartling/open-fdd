-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- avg_zone_temp.sql
SELECT
  equipment_id,
  AVG(zone_air_temperature) AS avg_zone_temp,
  MIN(zone_air_temperature) AS min_zone_temp,
  MAX(zone_air_temperature) AS max_zone_temp
FROM history
WHERE zone_air_temperature IS NOT NULL
GROUP BY equipment_id;
