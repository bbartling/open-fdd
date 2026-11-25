-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- filter_load.sql — AHU filter loading / fouling (#1783), applied by bound roles (never by equipment names).
--
-- Path per equipment, the first one with data:
--   filter_dp:  filter differential pressure above DP_DIRTY (Pa) with the fan on and, where zone_flow is bound,
--               airflow >= FLOW_FRAC x the series' own 90th percentile airflow (fan-on samples), so a start-up
--               spike at low flow is not a fault. A reading outside 0-2500 Pa is a sensor problem (SV-RANGE /
--               SV-FLATLINE), not a filter fault: that sample is never a fault here.
--   fan_effort: no filter DP; fan_power and zone_flow both bound. Advisory: fan effort (kW per L/s) above
--               EFFORT_RATIO x its own 10th percentile over fan-on samples at airflow >= FLOW_FRAC x the 90th
--               percentile. Fewer than 4 h of such samples -> assessment 'insufficient_baseline' (not assessed).
-- filter_path names the path; assessment is 'assessed' on either path.
-- Neither path -> assessment 'no_filter_inputs': fault_hours NULL, covered_hours 0 (never a silent pass).
-- Percentiles are the lowest value whose 1-based rank r satisfies r x 10 >= n x k (portable; no PERCENTILE_CONT).
-- Run-proof gated like the other air-side rules (#1608).
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
    filter_dp,
    fan_power,
    zone_flow,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN fan_cmd > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) - timestamp_utc
    )) AS dt_seconds
  FROM history
),
avail AS (
  SELECT equipment_id,
    CASE WHEN COUNT(filter_dp) > 0 THEN 'filter_dp'
         WHEN COUNT(fan_power) > 0 AND COUNT(zone_flow) > 0 THEN 'fan_effort'
         ELSE 'no_filter_inputs' END AS path
  FROM h
  GROUP BY equipment_id
),
flow_rank AS (
  SELECT equipment_id, zone_flow,
    ROW_NUMBER() OVER (PARTITION BY equipment_id ORDER BY zone_flow) AS rn,
    COUNT(*) OVER (PARTITION BY equipment_id) AS n
  FROM h
  WHERE fan_on = 1 AND zone_flow IS NOT NULL
),
flow_ref AS (
  -- 90th percentile airflow of the fan-on samples
  SELECT equipment_id, MIN(zone_flow) AS flow_ref
  FROM flow_rank
  WHERE rn * 10 >= n * 9
  GROUP BY equipment_id
),
e AS (
  SELECT
    h.*,
    fr.flow_ref,
    CASE WHEN h.fan_on = 1 AND h.fan_power > 0.0 AND h.zone_flow > 0.0
          AND h.zone_flow >= {{FLOW_FRAC}} * fr.flow_ref
         THEN h.fan_power / h.zone_flow ELSE NULL END AS effort
  FROM h
  LEFT JOIN flow_ref fr ON fr.equipment_id = h.equipment_id
),
effort_rank AS (
  SELECT equipment_id, effort,
    ROW_NUMBER() OVER (PARTITION BY equipment_id ORDER BY effort) AS rn,
    COUNT(*) OVER (PARTITION BY equipment_id) AS n
  FROM e
  WHERE effort IS NOT NULL
),
effort_base AS (
  -- 10th percentile fan effort: the clean-filter baseline of this window
  SELECT equipment_id, MIN(effort) AS effort_base
  FROM effort_rank
  WHERE rn * 10 >= n
  GROUP BY equipment_id
),
baseline_hours AS (
  SELECT equipment_id,
    SUM(CASE WHEN effort IS NOT NULL AND dt_seconds > 0.0 AND dt_seconds <= ({{MAX_GAP_HOURS}} * 3600.0)
             THEN dt_seconds ELSE 0.0 END) / 3600.0 AS hours
  FROM e
  GROUP BY equipment_id
),
assess AS (
  SELECT av.equipment_id,
    CASE WHEN av.path = 'no_filter_inputs' THEN 'no_filter_inputs'
         WHEN av.path = 'fan_effort' AND COALESCE(bh.hours, 0.0) < 4.0 THEN 'insufficient_baseline'
         ELSE 'assessed' END AS assessment,
    av.path,
    eb.effort_base
  FROM avail av
  LEFT JOIN effort_base eb ON eb.equipment_id = av.equipment_id
  LEFT JOIN baseline_hours bh ON bh.equipment_id = av.equipment_id
),
base AS (
  SELECT
    e.equipment_id,
    e.timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(run_proof, 0) <= 0.05 THEN 0
      WHEN e.fan_on = 0 THEN 0
      WHEN a.assessment = 'assessed' AND a.path = 'filter_dp' THEN CASE
        WHEN e.filter_dp IS NOT NULL AND e.filter_dp >= 0.0 AND e.filter_dp <= 2500.0 AND e.filter_dp > {{DP_DIRTY}}
         AND (e.zone_flow IS NULL OR e.flow_ref IS NULL OR e.zone_flow >= {{FLOW_FRAC}} * e.flow_ref) THEN 1
        ELSE 0 END
      WHEN a.assessment = 'assessed' AND a.path = 'fan_effort' THEN CASE
        WHEN e.effort IS NOT NULL AND e.effort > {{EFFORT_RATIO}} * a.effort_base THEN 1
        ELSE 0 END
      ELSE 0
    END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN e.run_proof > 0.05 THEN 1 ELSE 0 END AS proof_active
  FROM e
  JOIN assess a ON a.equipment_id = e.equipment_id
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
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT ax.assessment FROM assess ax WHERE ax.equipment_id = final.equipment_id) <> 'assessed' THEN NULL
       ELSE SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS fault_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT ax.assessment FROM assess ax WHERE ax.equipment_id = final.equipment_id) <> 'assessed' THEN 0.0
       ELSE SUM(held_seconds) / 3600.0 END AS covered_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT ax.assessment FROM assess ax WHERE ax.equipment_id = final.equipment_id) <> 'assessed' THEN 0.0
       ELSE SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS active_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT ax.assessment FROM assess ax WHERE ax.equipment_id = final.equipment_id) <> 'assessed' THEN NULL
       ELSE COALESCE(100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END)
                     / NULLIF(SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END), 0.0), 0.0) END AS fault_pct,
  (SELECT ax.assessment FROM assess ax WHERE ax.equipment_id = final.equipment_id) AS assessment,
  (SELECT ax.path FROM assess ax WHERE ax.equipment_id = final.equipment_id) AS filter_path
FROM final
GROUP BY equipment_id;
