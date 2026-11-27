-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc8_sat_mat_econ.sql — FC8 SAT vs MAT while economizing + confirm
WITH rp AS (
  -- Run proof (#1608): the input role operating_status is resolved from the model (own status, own command, feeding equipment).
  -- With the gate on and no proof bound at all, the equipment is SKIPPED: fault_hours NULL, covered_hours 0.
  SELECT equipment_id,
    CASE WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COUNT(operating_status) = 0 THEN 1 ELSE 0 END AS no_run_proof
  FROM history
  GROUP BY equipment_id
),
-- #1631: require_run_proof = 0 switches off only the resolved run-proof gate; the rule keeps its own fan condition,
-- fan-restart holdoff and active-coverage floor (as pandas: the operational gate is not the run-proof gate).
h AS (
  SELECT
    operating_status,
    equipment_id,
    timestamp_utc,
    discharge_air_temperature,
    mixed_air_temperature,
    COALESCE(outdoor_air_intake_damper_position_command, 0.0) AS outdoor_air_intake_damper_position_command,
    COALESCE(cooling_valve_position_command, 0.0) AS cooling_valve_position_command,
    supply_fan_command,
    supply_fan_operating_status,
        CASE
      WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN 1 ELSE 0 END
      WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > 0.5 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(operating_status, 0) <= 0.05 THEN 0
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN discharge_air_temperature IS NOT NULL AND mixed_air_temperature IS NOT NULL
       AND outdoor_air_intake_damper_position_command > {{ECON_MIN_POS}} AND cooling_valve_position_command < {{CLG_INACTIVE_MAX}}
       AND ABS(discharge_air_temperature - {{DELTA_SUPPLY_FAN}} - mixed_air_temperature) > SQRT({{EPS_SAT}} * {{EPS_SAT}} + {{EPS_MAT}} * {{EPS_MAT}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN operating_status > 0.05 THEN 1 ELSE 0 END AS proof_active
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    proof_active,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = f.equipment_id) = 1 THEN NULL ELSE CASE
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END END AS fault_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = f.equipment_id) = 1 THEN 0.0 ELSE SUM(f.held_seconds) / 3600.0 END AS covered_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = f.equipment_id) = 1 THEN 0.0 ELSE SUM(CASE WHEN f.proof_active = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0 END AS active_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = f.equipment_id) = 1 THEN NULL ELSE CASE
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE COALESCE(100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(CASE WHEN f.proof_active = 1 THEN f.held_seconds ELSE 0.0 END), 0.0), 0.0)
  END END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
