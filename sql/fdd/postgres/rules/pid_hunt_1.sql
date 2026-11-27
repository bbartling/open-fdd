-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- pid_hunt_1.sql — Suspected control-output hunting (rolling 1h metrics)
-- Matches pandas hunting_fault_mask: TV / span / cycles / reversals over
-- WINDOW_HOURS. The detection window is still a row frame (WINDOW_ROWS).
-- Fault hours integrate eligible forward deltas and do not add a phantom
-- interval after the last sample. {{WINDOW_ROWS}} / {{WINDOW_ROWS_PRECEDING}}
-- are derived from WINDOW_HOURS + POLL_SECONDS (literal ROWS bounds).
-- Control outputs arrive as PERCENT 0-100 (the ingest converts a fraction source once). Span, deadband
-- and variation thresholds are percent points; do not scale the column again.
-- exactly here, once, because the *_PCT parameters (span, deadband, total variation) are percent points.
WITH rp AS (
  -- Run proof (#1608): the input role operating_status is resolved from the model (own status, own command, feeding equipment).
  -- With the gate on and no proof bound at all, the equipment is SKIPPED: fault_hours NULL, covered_hours 0.
  SELECT equipment_id,
    CASE WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COUNT(operating_status) = 0 THEN 1 ELSE 0 END AS no_run_proof
  FROM history
  GROUP BY equipment_id
),
rps AS (
  SELECT equipment_id, timestamp_utc, MAX(operating_status) AS operating_status
  FROM history
  GROUP BY equipment_id, timestamp_utc
),
h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN outdoor_air_intake_damper_position_command IS NOT NULL THEN
        outdoor_air_intake_damper_position_command
      WHEN cooling_valve_position_command IS NOT NULL THEN
        cooling_valve_position_command
      WHEN heating_valve_position_command IS NOT NULL THEN
        heating_valve_position_command
      WHEN damper_position IS NOT NULL THEN
        damper_position
      ELSE NULL
    END AS out_pct,
    LAG(
      CASE
        WHEN outdoor_air_intake_damper_position_command IS NOT NULL THEN
          outdoor_air_intake_damper_position_command
        WHEN cooling_valve_position_command IS NOT NULL THEN
          cooling_valve_position_command
        WHEN heating_valve_position_command IS NOT NULL THEN
          heating_valve_position_command
        WHEN damper_position IS NOT NULL THEN
          damper_position
        ELSE NULL
      END
    ) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_out,
    COALESCE(operating_mode_status, 1.0) AS loop_on,
    CASE
      WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN 1 ELSE 0 END
      WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > 0.5 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
deltas AS (
  SELECT
    *,
    CASE
      WHEN prev_out IS NULL OR out_pct IS NULL THEN NULL
      WHEN ABS(out_pct - prev_out) >= {{CHANGE_DEADBAND_PCT}} THEN out_pct - prev_out
      ELSE 0.0
    END AS sig_delta
  FROM h
),
steps AS (
  SELECT
    *,
    CASE
      WHEN sig_delta IS NULL THEN 0
      ELSE ABS(sig_delta)
    END AS abs_step,
    CASE
      WHEN sig_delta IS NULL OR sig_delta = 0 THEN 0
      WHEN LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) = 0 THEN 0
      WHEN sig_delta * LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) < 0 THEN 1
      ELSE 0
    END AS reversal_event
  FROM deltas
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    out_pct,
    fan_on,
    loop_on,
    COUNT(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS n_samples,
    SUM(abs_step) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS tv,
    MAX(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    )
      - MIN(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS span,
    SUM(reversal_event) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS reversals
  FROM steps
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(operating_status, 0) <= 0.05 THEN 0
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN loop_on IS NOT NULL AND loop_on <= 0.05 THEN 0
      WHEN out_pct IS NULL THEN 0
      WHEN n_samples < CAST(CEIL({{WINDOW_ROWS}} * {{MINIMUM_COVERAGE_PCT}} / 100.0) AS INT) THEN 0
      WHEN span < {{MINIMUM_SPAN_PCT}} THEN 0
      WHEN tv < {{TOTAL_VARIATION_FAULT_PCT}} THEN 0
      WHEN span <= 0 THEN 0
      WHEN (tv / (2.0 * NULLIF(span, 0))) < {{MINIMUM_EQUIVALENT_CYCLES}} THEN 0
      WHEN reversals < {{MINIMUM_REVERSALS}} THEN 0
      ELSE 1
    END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN operating_status > 0.05 THEN 1 ELSE 0 END AS proof_active
  FROM win
  LEFT JOIN rps USING (equipment_id, timestamp_utc)
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
SELECT
  equipment_id,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN NULL ELSE SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS fault_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN 0.0 ELSE SUM(held_seconds) / 3600.0 END AS covered_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN 0.0 ELSE SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS active_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN NULL ELSE COALESCE(100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END), 0.0), 0.0) END AS fault_pct
FROM final
GROUP BY equipment_id;
