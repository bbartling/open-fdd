-- chw_noload_1.sql — Chiller running with no building load
-- When both zone and AHU load-satisfied flags are null, emit
-- SKIPPED_MISSING_ROLES (do not PASS 0 h). Prefer load_satisfaction
-- enrichment pandas uses when those columns are mapped.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chiller_status,
    chiller_cmd,
    chw_pump_status,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump_cmd,
    building_zone_load_satisfied,
    building_ahu_load_satisfied,
    CASE
      WHEN building_zone_load_satisfied IS NOT NULL
        OR building_ahu_load_satisfied IS NOT NULL THEN 1
      ELSE 0
    END AS sat_present,
    COALESCE(building_zone_load_satisfied, building_ahu_load_satisfied) AS load_sat
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_present,
    load_sat,
    CASE
      WHEN chiller_status IS NULL AND chiller_cmd IS NULL
           AND chw_pump_status IS NULL AND pump_cmd IS NULL THEN NULL
      WHEN COALESCE(chiller_status, 0) > 0.05 THEN 1
      WHEN COALESCE(chiller_cmd, 0) > 0.05 THEN 1
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
    sat_present,
    CAST(CASE
      WHEN sat_present = 0 THEN 0
      WHEN running IS NULL OR load_sat IS NULL THEN 0
      WHEN running = 1 AND load_sat > {{LOAD_SAT_HI}} THEN 1
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
    sat_present,
    CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours,
  CASE
    WHEN MAX(sat_present) = 0 THEN 'SKIPPED_MISSING_ROLES'
    WHEN SUM(confirmed) > 0 THEN 'FAULT'
    ELSE 'PASS'
  END AS status
FROM final
GROUP BY equipment_id;
