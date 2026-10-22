-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
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
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
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
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    sat_present,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct,
  CASE
    WHEN MAX(sat_present) = 0 THEN 'SKIPPED_MISSING_ROLES'
    WHEN SUM(confirmed) > 0 THEN 'FAULT'
    ELSE 'PASS'
  END AS status
FROM final
GROUP BY equipment_id;
