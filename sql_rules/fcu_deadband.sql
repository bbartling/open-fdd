-- FCU-DEADBAND — pass-through FCU setpoints remain site-native Celsius
SELECT equipment_id,
  SUM(CASE WHEN cooling_sp IS NOT NULL AND heating_sp IS NOT NULL
    AND cooling_sp - heating_sp < {{DEADBAND_C}} THEN 1 ELSE 0 END)
    * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM history
GROUP BY equipment_id;

