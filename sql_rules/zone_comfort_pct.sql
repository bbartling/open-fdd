-- zone_comfort_pct.sql
SELECT
  equipment_id,
  100.0 * SUM(CASE WHEN zone_t >= {{ZONE_T_LO}} AND zone_t <= {{ZONE_T_HI}} THEN 1 ELSE 0 END) / COUNT(*) AS comfort_pct
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;
