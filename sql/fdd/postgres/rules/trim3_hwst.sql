-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim3_hwst.sql — HWST trim advisory
WITH rp AS (
  -- Run proof (#1608): the input role run_proof is resolved from the model (own status, own command, feeding equipment).
  -- With the gate on and no proof bound at all, the equipment is SKIPPED: fault_hours NULL, covered_hours 0.
  SELECT equipment_id,
    CASE WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COUNT(run_proof) = 0 THEN 1 ELSE 0 END AS no_run_proof
  FROM history
  GROUP BY equipment_id
),
h AS (
  SELECT
    run_proof,
    equipment_id,
    timestamp_utc,
    hw_supply_t,
    hw_reset_request_sum,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 0.0630902 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN chw_pump_cmd > 0.05 THEN 1 ELSE 0 END
      -- #1631: no legacy plant point bound = unknown, not OFF; the resolved run_proof gate above decides
      ELSE NULL
    END AS proof_on
  FROM history
),
started AS (
  -- #1758 startup holdoff (pandas operational_gate.apply_startup_delay): a sample counts only once the plant proof (else
  -- the resolved run proof) has been on for STARTUP_DELAY_ROWS samples in a row, this one included; the first sample of
  -- the series counts as a start. No proof at all is unknown, not OFF (#1631).
  SELECT
    *,
    CASE
      WHEN MIN(COALESCE(proof_on, CASE WHEN run_proof IS NULL OR run_proof > 0.05 THEN 1 ELSE 0 END))
             OVER (PARTITION BY equipment_id ORDER BY timestamp_utc
             ROWS BETWEEN {{STARTUP_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) = 1
       AND COUNT(*) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc
             ROWS BETWEEN {{STARTUP_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) > {{STARTUP_DELAY_ROWS_PRECEDING}}
      THEN 1 ELSE 0
    END AS startup_ok
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(run_proof, 0) <= 0.05 THEN 0
      WHEN proof_on = 0 THEN 0
      WHEN startup_ok = 0 THEN 0
      WHEN hw_supply_t IS NULL THEN 0
      WHEN hw_supply_t > {{HWST_HI}}
       AND hw_reset_request_sum <= {{REQUEST_LO}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN run_proof > 0.05 THEN 1 ELSE 0 END AS proof_active
  FROM started
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
