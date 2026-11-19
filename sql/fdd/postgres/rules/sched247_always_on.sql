-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sched247_always_on.sql — Always-on fan or pump runtime (#1670)
-- Unit-free: ALWAYS_ON_PCT is a fraction of proven run time.
--
-- Proof per sample: the first non-NULL status (fan, pump, chw pump, chiller, compressor, chiller current) wins over
-- the commands (tower fan, fan, chw pump); run when > 0.05 (sql/fdd/run_proof.json threshold); a sample with
-- neither is UNKNOWN (never a proven OFF). Each sample holds forward to the next one; a hold longer than
-- MAX_GAP_HOURS, and the last sample, hold nothing.
--
-- Durations (hours): window = first..last history row of the equipment (the observed window);
-- proven_on / proven_off = held time with known proof; unknown = window - proven_on - proven_off.
-- Completeness: the verdict needs proven time >= 0.9 * max(window, 24 h). "Always on" is judged on the
-- observed window but never on less than one day of proof. Otherwise assessment = 'insufficient_proof'
-- (or 'no_proof' when nothing is known) and fault_hours / fault_pct are NULL.
-- Qualifier: proven_on / (proven_on + proven_off) >= ALWAYS_ON_PCT (time-weighted). Fault time is the
-- confirmed proven-ON time (CONFIRM_SECONDS streaks) of a qualifying equipment.
WITH proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_status IS NOT NULL THEN CASE WHEN chw_pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN compressor_status IS NOT NULL THEN CASE WHEN compressor_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_current IS NOT NULL THEN CASE WHEN chiller_current > 0.05 THEN 1 ELSE 0 END
      WHEN tower_fan_cmd IS NOT NULL THEN CASE WHEN tower_fan_cmd > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN fan_cmd > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN chw_pump_cmd > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS INT) AS on_bit
  FROM history
),
stepped AS (
  SELECT
    proof.*,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) - timestamp_utc
    )) AS dt_seconds
  FROM proof
),
held AS (
  SELECT
    stepped.*,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) OR on_bit IS NULL
      THEN 0.0 ELSE dt_seconds
    END AS held_seconds,
    CASE WHEN dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1 ELSE 0 END AS gap_after
  FROM stepped
),
summary AS (
  SELECT
    equipment_id,
    EXTRACT(EPOCH FROM (MAX(timestamp_utc) - MIN(timestamp_utc))) AS window_seconds,
    SUM(CASE WHEN on_bit = 1 THEN held_seconds ELSE 0.0 END) AS on_seconds,
    SUM(CASE WHEN on_bit = 0 THEN held_seconds ELSE 0.0 END) AS off_seconds
  FROM held
  GROUP BY equipment_id
),
verdict AS (
  SELECT
    summary.*,
    CASE
      WHEN on_seconds + off_seconds <= 0.0 THEN 'no_proof'
      WHEN on_seconds + off_seconds < 0.9 * (CASE WHEN window_seconds > 86400.0 THEN window_seconds ELSE 86400.0 END)
        THEN 'insufficient_proof'
      ELSE 'assessed'
    END AS assessment
  FROM summary
),
base AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    h.held_seconds,
    h.gap_after,
    CAST(CASE
      WHEN v.assessment = 'assessed'
       AND v.on_seconds / (v.on_seconds + v.off_seconds) >= {{ALWAYS_ON_PCT}}
       AND h.on_bit = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM held h
  JOIN verdict v ON v.equipment_id = h.equipment_id
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
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
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    timestamp_utc,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  v.equipment_id,
  CASE WHEN v.assessment = 'assessed' THEN t.fault_seconds / 3600.0 END AS fault_hours,
  (v.on_seconds + v.off_seconds) / 3600.0 AS covered_hours,
  CASE WHEN v.assessment = 'assessed'
    THEN 100.0 * t.fault_seconds / NULLIF(v.on_seconds + v.off_seconds, 0.0) END AS fault_pct,
  v.window_seconds / 3600.0 AS window_hours,
  v.on_seconds / 3600.0 AS proven_on_hours,
  v.off_seconds / 3600.0 AS proven_off_hours,
  CASE WHEN v.window_seconds - v.on_seconds - v.off_seconds > 0.0
    THEN (v.window_seconds - v.on_seconds - v.off_seconds) / 3600.0 ELSE 0.0 END AS unknown_hours,
  v.assessment
FROM verdict v
JOIN (
  SELECT equipment_id, SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) AS fault_seconds
  FROM final
  GROUP BY equipment_id
) t ON t.equipment_id = v.equipment_id;
