-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- short_cycle.sql — Boiler / compressor short cycling (#1781): too many starts in the trailing hour, or repeated
-- on-times shorter than MIN_ON_SECONDS, read from proven run status (never a command).
--
-- Proof, the first candidate that is ever on (> 0.05), else the first one bound: boiler_operating_status, compressor_operating_status,
-- chiller_operating_status, chiller_electric_current > MECH_AMPS_MIN, chiller_electric_power > MECH_POWER_KW_MIN. None bound -> assessment
-- 'no_run_status': fault_hours NULL, covered_hours 0 (never a silent pass).
--
-- Duty-aware: a status sample is the on-fraction of its interval (NF resamples a 0/1 status by AVERAGE, so a bucket
-- holds a duty, never a max). Duty <= 0.05 is off, >= 0.95 is on for the whole interval, anything between is a
-- partial sample that must hold a start or a stop. Starts are the FEWEST consistent with the duties: one on-period
-- (cycle) spans whole-on samples and can begin or end only inside a partial sample, so in a run of non-off samples a
-- partial sample closes the cycle that is already open and the next sample opens a new one. A cycle's start counts
-- when it is seen (an off sample before it, or a stop inside the run); its on-time is the duty-weighted held time.
-- A completed cycle (start and stop both seen) shorter than MIN_ON_SECONDS is a short cycle.
--
-- A sample is in fault when, over the trailing hour (t - 3600 s, t], starts > MAX_STARTS_PER_HOUR or short cycles
-- >= MIN_SHORT_CYCLES. No confirmation delay: the counts already span the hour. On a trend coarser than
-- MAX_INTERVAL_SECONDS the counts are floors: a sample whose hour holds such an interval is fault time when the
-- floor reaches the threshold (assessment 'coarse_floor'), and otherwise unknown (not covered). Nothing covered ->
-- 'insufficient_trend' (NOT ASSESSED).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    EXTRACT(EPOCH FROM timestamp_utc) AS epoch_s,
    boiler_operating_status AS c1,
    compressor_operating_status AS c2,
    chiller_operating_status AS c3,
    CASE WHEN chiller_electric_current IS NULL THEN NULL WHEN chiller_electric_current > {{MECH_AMPS_MIN}} THEN 1.0 ELSE 0.0 END AS c4,
    CASE WHEN chiller_electric_power IS NULL THEN NULL WHEN chiller_electric_power > {{MECH_POWER_KW_MIN}} THEN 1.0 ELSE 0.0 END AS c5
  FROM history
),
pick AS (
  SELECT equipment_id,
    CASE
      WHEN MAX(c1) > 0.05 THEN 1 WHEN MAX(c2) > 0.05 THEN 2 WHEN MAX(c3) > 0.05 THEN 3
      WHEN MAX(c4) > 0.05 THEN 4 WHEN MAX(c5) > 0.05 THEN 5
      WHEN COUNT(c1) > 0 THEN 1 WHEN COUNT(c2) > 0 THEN 2 WHEN COUNT(c3) > 0 THEN 3
      WHEN COUNT(c4) > 0 THEN 4 WHEN COUNT(c5) > 0 THEN 5
      ELSE 0
    END AS proof_kind
  FROM h
  GROUP BY equipment_id
),
proof AS (
  SELECT h.equipment_id, h.timestamp_utc, h.epoch_s,
    CASE p.proof_kind WHEN 1 THEN h.c1 WHEN 2 THEN h.c2 WHEN 3 THEN h.c3 WHEN 4 THEN h.c4 WHEN 5 THEN h.c5 ELSE NULL END AS v
  FROM h
  JOIN pick p ON p.equipment_id = h.equipment_id
),
nb AS (
  -- valid proof samples only; neighbours are the previous / next valid sample
  SELECT
    equipment_id,
    timestamp_utc,
    epoch_s,
    CASE WHEN v < 0.0 THEN 0.0 WHEN v >= 1.0 THEN 1.0 ELSE v END AS u,
    CASE WHEN v <= 0.05 THEN 0 WHEN v >= 0.95 THEN 2 ELSE 1 END AS cls,
    LAG(CASE WHEN v <= 0.05 THEN 0 WHEN v >= 0.95 THEN 2 ELSE 1 END)
      OVER (PARTITION BY equipment_id ORDER BY epoch_s) AS prev_cls,
    LEAD(CASE WHEN v <= 0.05 THEN 0 WHEN v >= 0.95 THEN 2 ELSE 1 END)
      OVER (PARTITION BY equipment_id ORDER BY epoch_s) AS next_cls,
    epoch_s - LAG(epoch_s) OVER (PARTITION BY equipment_id ORDER BY epoch_s) AS dt_back,
    LEAD(epoch_s) OVER (PARTITION BY equipment_id ORDER BY epoch_s) - epoch_s AS dt_fwd
  FROM proof
  WHERE v IS NOT NULL
),
runs AS (
  SELECT
    nb.*,
    -- a gap longer than MAX_GAP_HOURS breaks the sequence: nothing is known across it
    CASE WHEN dt_back IS NULL OR dt_back > {{MAX_GAP_HOURS}} * 3600.0 THEN 1 ELSE 0 END AS brk,
    CASE WHEN dt_fwd IS NOT NULL AND dt_fwd > 0.0 AND dt_fwd <= {{MAX_GAP_HOURS}} * 3600.0 THEN dt_fwd ELSE 0.0 END AS held_s,
    CASE WHEN dt_fwd IS NOT NULL AND dt_fwd <= {{MAX_GAP_HOURS}} * 3600.0 AND next_cls = 0 THEN 1 ELSE 0 END AS off_next,
    CASE WHEN dt_fwd IS NOT NULL AND dt_fwd > {{MAX_INTERVAL_SECONDS}} AND dt_fwd <= {{MAX_GAP_HOURS}} * 3600.0 THEN 1 ELSE 0 END AS coarse
  FROM nb
),
pos AS (
  -- non-off samples; a run is a sequence of them with no off sample and no gap
  SELECT
    runs.*,
    CASE WHEN brk = 1 OR prev_cls = 0 THEN 1 ELSE 0 END AS run_start,
    CASE WHEN brk = 0 AND prev_cls = 0 THEN 1 ELSE 0 END AS seen_rise,
    CASE WHEN cls = 1 AND (brk = 1 OR prev_cls <> 1) THEN 1 ELSE 0 END AS chain_start
  FROM runs
  WHERE cls > 0
),
chains AS (
  SELECT
    pos.*,
    SUM(chain_start) OVER (PARTITION BY equipment_id ORDER BY epoch_s ROWS UNBOUNDED PRECEDING) AS chain_id
  FROM pos
),
chain_pos AS (
  -- k: position of a partial sample in its chain of consecutive partial samples
  SELECT
    chains.*,
    ROW_NUMBER() OVER (PARTITION BY equipment_id, chain_id, cls ORDER BY epoch_s) - 1 AS k,
    MAX(CASE WHEN chain_start = 1 THEN run_start ELSE 0 END) OVER (PARTITION BY equipment_id, chain_id) AS chain_at_run_start
  FROM chains
),
closing AS (
  -- a partial sample closes the open cycle unless it opened that cycle itself
  SELECT
    chain_pos.*,
    CASE
      WHEN cls = 1 AND chain_at_run_start = 1 AND k % 2 = 1 THEN 1
      WHEN cls = 1 AND chain_at_run_start = 0 AND k % 2 = 0 THEN 1
      ELSE 0
    END AS closes
  FROM chain_pos
),
opens AS (
  SELECT
    closing.*,
    CASE
      WHEN run_start = 1 THEN 1
      WHEN LAG(closes) OVER (PARTITION BY equipment_id ORDER BY epoch_s) = 1 THEN 1
      ELSE 0
    END AS cycle_start
  FROM closing
),
cycles AS (
  SELECT
    opens.*,
    CASE WHEN cycle_start = 1 AND (run_start = 0 OR seen_rise = 1) THEN 1 ELSE 0 END AS start_evt,
    SUM(cycle_start) OVER (PARTITION BY equipment_id ORDER BY epoch_s ROWS UNBOUNDED PRECEDING) AS cycle_id
  FROM opens
),
cycle_sum AS (
  SELECT
    equipment_id,
    MAX(timestamp_utc) AS end_ts,
    MAX(start_evt) AS seen_start,
    MAX(CASE WHEN closes = 1 OR off_next = 1 THEN 1 ELSE 0 END) AS seen_stop,
    SUM(u * held_s) AS on_s
  FROM cycles
  GROUP BY equipment_id, cycle_id
),
ev AS (
  SELECT
    r.equipment_id,
    r.timestamp_utc,
    r.epoch_s,
    r.coarse,
    COALESCE(c.start_evt, 0) AS start_evt,
    CASE WHEN s.equipment_id IS NOT NULL THEN 1 ELSE 0 END AS short_evt
  FROM runs r
  LEFT JOIN cycles c
    ON c.equipment_id = r.equipment_id AND c.timestamp_utc = r.timestamp_utc
  LEFT JOIN cycle_sum s
    ON s.equipment_id = r.equipment_id AND s.end_ts = r.timestamp_utc
   AND s.seen_start = 1 AND s.seen_stop = 1 AND s.on_s < {{MIN_ON_SECONDS}}
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    SUM(start_evt) OVER (PARTITION BY equipment_id ORDER BY epoch_s RANGE BETWEEN 3599.999 PRECEDING AND CURRENT ROW) AS starts_h,
    SUM(short_evt) OVER (PARTITION BY equipment_id ORDER BY epoch_s RANGE BETWEEN 3599.999 PRECEDING AND CURRENT ROW) AS short_h,
    MAX(coarse) OVER (PARTITION BY equipment_id ORDER BY epoch_s RANGE BETWEEN 3599.999 PRECEDING AND CURRENT ROW) AS coarse_h
  FROM ev
),
judged AS (
  SELECT
    equipment_id,
    timestamp_utc,
    coarse_h,
    CASE WHEN starts_h > {{MAX_STARTS_PER_HOUR}} OR short_h >= {{MIN_SHORT_CYCLES}} THEN 1 ELSE 0 END AS raw_fault
  FROM win
),
held AS (
  -- forward sample-and-hold over every history row (the last row and a gap longer than MAX_GAP_HOURS hold nothing)
  SELECT
    equipment_id,
    timestamp_utc,
    LEAD(epoch_s) OVER (PARTITION BY equipment_id ORDER BY epoch_s) - epoch_s AS dt_seconds
  FROM h
),
final AS (
  SELECT
    hd.equipment_id,
    hd.timestamp_utc,
    CASE
      WHEN j.equipment_id IS NULL THEN 0.0
      WHEN j.coarse_h = 1 AND j.raw_fault = 0 THEN 0.0
      WHEN hd.dt_seconds IS NULL OR hd.dt_seconds <= 0.0 OR hd.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 0.0
      ELSE hd.dt_seconds
    END AS held_seconds,
    COALESCE(j.raw_fault, 0) AS confirmed,
    CASE WHEN j.coarse_h = 1 AND j.raw_fault = 1 THEN 1 ELSE 0 END AS floor_fault
  FROM held hd
  LEFT JOIN judged j
    ON j.equipment_id = hd.equipment_id AND j.timestamp_utc = hd.timestamp_utc
)
SELECT
  p.equipment_id,
  CASE WHEN p.proof_kind = 0 OR COALESCE(a.covered_s, 0.0) <= 0.0 THEN NULL ELSE CAST(a.fault_s / 3600.0 AS DOUBLE PRECISION) END AS fault_hours,
  CASE WHEN p.proof_kind = 0 OR COALESCE(a.covered_s, 0.0) <= 0.0 THEN 0.0 ELSE CAST(a.covered_s / 3600.0 AS DOUBLE PRECISION) END AS covered_hours,
  CASE WHEN p.proof_kind = 0 OR COALESCE(a.covered_s, 0.0) <= 0.0 THEN NULL ELSE CAST(100.0 * a.fault_s / a.covered_s AS DOUBLE PRECISION) END AS fault_pct,
  CASE
    WHEN p.proof_kind = 0 THEN 'no_run_status'
    WHEN COALESCE(a.covered_s, 0.0) <= 0.0 THEN 'insufficient_trend'
    WHEN a.floor_fault = 1 THEN 'coarse_floor'
    ELSE 'assessed'
  END AS assessment
FROM pick p
LEFT JOIN (
  SELECT
    equipment_id,
    SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) AS fault_s,
    SUM(held_seconds) AS covered_s,
    MAX(CASE WHEN floor_fault = 1 AND held_seconds > 0.0 THEN 1 ELSE 0 END) AS floor_fault
  FROM final
  GROUP BY equipment_id
) a ON a.equipment_id = p.equipment_id;
