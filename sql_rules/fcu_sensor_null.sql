-- FCU-SENSOR-NULL — own zone setpoint exists while a mapped zone sensor is predominantly null.
-- The runner rewrites this file to zero hours when zone_t is absent from history.
WITH coverage AS (
  SELECT equipment_id,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL THEN 1 ELSE 0 END) AS eligible_rows,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL AND zone_t IS NULL THEN 1 ELSE 0 END) AS null_rows
  FROM history
  GROUP BY equipment_id
)
SELECT equipment_id,
  CASE WHEN eligible_rows > 0 AND CAST(null_rows AS DOUBLE) / eligible_rows >= {{NULL_FRACTION}}
    THEN null_rows * {{POLL_SECONDS}} / 3600.0 ELSE 0.0 END AS fault_hours
FROM coverage;
