-- chw_noload_1.sql — Chiller running with no building load
-- Mechanical proof (chiller status, CHW pump status, or CHW pump command) while
-- the building-wide load-satisfied flag is true: the plant is making chilled
-- water nobody is asking for.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chiller_status,
    chw_pump_status,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump_cmd,
    building_zone_load_satisfied
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    building_zone_load_satisfied,
    CASE
      WHEN chiller_status IS NULL AND chw_pump_status IS NULL AND pump_cmd IS NULL THEN NULL
      WHEN COALESCE(chiller_status, 0) > 0.05 THEN 1
      WHEN COALESCE(chw_pump_status, 0) > 0.05 THEN 1
      WHEN COALESCE(pump_cmd, 0) > 0.05 THEN 1
      ELSE 0
    END AS running
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN running IS NULL OR building_zone_load_satisfied IS NULL THEN 0
      WHEN running = 1 AND building_zone_load_satisfied > 0.5 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM base
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;
