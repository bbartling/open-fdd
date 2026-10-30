-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw3_supply_band.sql — Plant supply temp outside deadband
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t, chw_supply_sp,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status, chw_flow
  FROM history
),
proof AS (
  SELECT *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 0.0630902 THEN 1 ELSE 0 END
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
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_supply_t IS NULL OR chw_supply_sp IS NULL THEN 0
      WHEN ABS(chw_supply_t - chw_supply_sp) > {{SP_BAND}} THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
