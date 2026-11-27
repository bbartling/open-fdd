-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- xs_mix.sql — Cross-sensor consistency (#1780): mixed-air temperature outside the outdoor / return mixing envelope.
-- A sensor or mapping finding, not an economizer fault: with the fan proven on, mixed_air_temperature must lie in
--   [min(outdoor_air_intake_temperature, return_air_temperature) - MIX_BAND, max(outdoor_air_intake_temperature, return_air_temperature) + MIX_BAND]
-- at any damper position (closed: mixed_air_temperature ~ return_air_temperature, open: mixed_air_temperature ~ outdoor_air_intake_temperature). Fan on: supply_fan_operating_status, else supply_fan_command, else the run proof.
-- No sample with mixed_air_temperature, outdoor_air_intake_temperature and return_air_temperature together -> assessment 'no_temperatures'; no run proof bound (gate on) ->
-- 'no_run_proof'. Not assessed: fault_hours NULL, covered_hours 0 (never a silent pass). Run-proof gated (#1608).
WITH rp AS (
  SELECT equipment_id,
    CASE WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COUNT(operating_status) = 0 THEN 1 ELSE 0 END AS no_run_proof
  FROM history
  GROUP BY equipment_id
),
h AS (
  SELECT
    operating_status,
    equipment_id,
    timestamp_utc,
    mixed_air_temperature,
    CASE WHEN outdoor_air_intake_temperature IS NULL OR return_air_temperature IS NULL THEN NULL WHEN outdoor_air_intake_temperature < return_air_temperature THEN outdoor_air_intake_temperature ELSE return_air_temperature END AS env_lo,
    CASE WHEN outdoor_air_intake_temperature IS NULL OR return_air_temperature IS NULL THEN NULL WHEN outdoor_air_intake_temperature > return_air_temperature THEN outdoor_air_intake_temperature ELSE return_air_temperature END AS env_hi,
    CASE
      WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN 1 ELSE 0 END
      WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
inputs AS (
  SELECT h.equipment_id,
    CASE
      WHEN SUM(CASE WHEN h.mixed_air_temperature IS NOT NULL AND h.env_lo IS NOT NULL THEN 1 ELSE 0 END) = 0 THEN 'no_temperatures'
      WHEN MAX(rp.no_run_proof) = 1 THEN 'no_run_proof'
      ELSE 'assessed'
    END AS assessment
  FROM h
  JOIN rp ON rp.equipment_id = h.equipment_id
  GROUP BY h.equipment_id
),
base AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    i.assessment,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(operating_status, 0) <= 0.05 THEN 0
      WHEN h.fan_on = 0 THEN 0
      WHEN h.mixed_air_temperature IS NULL OR h.env_lo IS NULL THEN 0
      WHEN h.mixed_air_temperature < h.env_lo - {{MIX_BAND}} THEN 1
      WHEN h.mixed_air_temperature > h.env_hi + {{MIX_BAND}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN operating_status > 0.05 THEN 1 ELSE 0 END AS proof_active
  FROM h
  JOIN inputs i ON i.equipment_id = h.equipment_id
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
    assessment,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  CASE WHEN MAX(assessment) = 'assessed'
       THEN SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 ELSE NULL END AS fault_hours,
  CASE WHEN MAX(assessment) = 'assessed' THEN SUM(held_seconds) / 3600.0 ELSE 0.0 END AS covered_hours,
  CASE WHEN MAX(assessment) = 'assessed'
       THEN SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 ELSE 0.0 END AS active_hours,
  CASE WHEN MAX(assessment) = 'assessed'
       THEN COALESCE(100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END)
                     / NULLIF(SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END), 0.0), 0.0)
       ELSE NULL END AS fault_pct,
  MAX(assessment) AS assessment
FROM final
GROUP BY equipment_id;
