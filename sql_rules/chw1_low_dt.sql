-- chw1_low_dt.sql — Low chilled-water ΔT
-- Operational proof required: status / current / power / flow / pump cmd.
-- Missing proof → 0 fault hours (pandas twin returns SKIPPED_MISSING_ROLES).
-- Proven off (zeros) → 0 fault hours.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t, chw_return_t,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    chiller_status,
    chiller_current,
    chiller_amps,
    chiller_power,
    chw_flow,
    pump_status
  FROM history
),
proof AS (
  SELECT
    *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_current IS NOT NULL THEN CASE WHEN chiller_current > 0.5 THEN 1 ELSE 0 END
      WHEN chiller_amps IS NOT NULL THEN CASE WHEN chiller_amps > 0.5 THEN 1 ELSE 0 END
      WHEN chiller_power IS NOT NULL THEN CASE WHEN chiller_power > 0.5 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN chw_supply_t IS NULL OR chw_return_t IS NULL THEN 0
      WHEN proof_on IS NULL THEN 0
      WHEN proof_on = 0 THEN 0
      WHEN (chw_return_t - chw_supply_t) < {{MIN_DT}} THEN 1
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
