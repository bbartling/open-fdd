-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fault_elapsed_hours.sql — comfort fault elapsed rollup
-- Out-of-band zone temperature holds forward until the next sample.
-- Gaps longer than MAX_GAP_HOURS are unknown (not fault, not covered).
WITH ordered AS (
  SELECT
    equipment_id,
    zone_t,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
  WHERE zone_t IS NOT NULL
),
held AS (
  SELECT
    equipment_id,
    zone_t,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM ordered
)
SELECT
  equipment_id,
  SUM(CASE WHEN zone_t < 68.0 OR zone_t > 76.0 THEN 1 ELSE 0 END) AS fault_samples,
  SUM(CASE
    WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN held_seconds
    ELSE 0.0
  END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE
    WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN held_seconds
    ELSE 0.0
  END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM held
GROUP BY equipment_id;
