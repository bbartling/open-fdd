-- econ1_stuck_closed.sql — ECON-1 economizer stuck closed
WITH h AS (
  SELECT
    equipment_id,
    oa_t,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_cmd,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_damper_pct
  FROM history
)
SELECT
  equipment_id,
  SUM(CASE
    WHEN fan_cmd > 0.01 AND oa_damper_pct IS NOT NULL AND oa_t IS NOT NULL
     AND oa_damper_pct < 0.05 AND oa_t > {{ECON1_OAT_MIN}}
    THEN 1 ELSE 0 END) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM h
GROUP BY equipment_id;
