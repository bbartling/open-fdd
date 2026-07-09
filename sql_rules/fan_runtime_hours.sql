-- fan_runtime_hours.sql
-- Fan runtime hours: fan_cmd normalized > 0.05
-- Output: equipment_id, fan_runtime_hours, total_hours

WITH h AS (
  SELECT
    equipment_id,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_cmd
  FROM history
)
SELECT
  equipment_id,
  SUM(CASE WHEN fan_cmd > 0.05 THEN 1 ELSE 0 END) * {{POLL_SECONDS}} / 3600.0 AS fan_runtime_hours,
  COUNT(*) * {{POLL_SECONDS}} / 3600.0 AS total_hours
FROM h
WHERE fan_cmd IS NOT NULL
GROUP BY equipment_id;
