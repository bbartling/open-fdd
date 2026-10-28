-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- zone_comfort_pct.sql
-- Comfort is the share of eligible elapsed time inside the band, not a row count.
-- History `zone_t` is admitted to pack °F before this rule runs; band placeholders
-- ZONE_T_LO / ZONE_T_HI are °F. Analytics RCx rank uses declared sample units separately.
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
  100.0 * SUM(CASE
    WHEN zone_t >= {{ZONE_T_LO}} AND zone_t <= {{ZONE_T_HI}} THEN held_seconds
    ELSE 0.0
  END) / NULLIF(SUM(held_seconds), 0.0) AS comfort_pct
FROM held
GROUP BY equipment_id;
