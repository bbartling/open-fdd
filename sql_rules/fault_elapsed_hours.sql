-- fault_elapsed_hours.sql — comfort fault sample rollup
SELECT
  equipment_id,
  SUM(CASE WHEN zone_t < 68.0 OR zone_t > 76.0 THEN 1 ELSE 0 END) AS fault_samples,
  SUM(CASE WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN 1 ELSE 0 END) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;
