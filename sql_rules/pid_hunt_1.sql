-- pid_hunt_1.sql — Suspected control-output hunting (rolling 1h metrics)
-- Matches pandas hunting_fault_mask: TV / span / cycles / reversals over
-- WINDOW_HOURS. Sample-to-sample Δ alone under-counts the golden hangover
-- window (0.917h vs 1.0h). {{WINDOW_ROWS}} / {{WINDOW_ROWS_PRECEDING}} are
-- derived from WINDOW_HOURS + POLL_SECONDS (DataFusion needs literal ROWS).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN oa_damper_pct IS NOT NULL THEN
        CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct ELSE oa_damper_pct * 100.0 END
      WHEN clg_valve_pct IS NOT NULL THEN
        CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct ELSE clg_valve_pct * 100.0 END
      WHEN htg_valve_pct IS NOT NULL THEN
        CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct ELSE htg_valve_pct * 100.0 END
      WHEN damper_pct IS NOT NULL THEN
        CASE WHEN damper_pct > 1.0 THEN damper_pct ELSE damper_pct * 100.0 END
      ELSE NULL
    END AS out_pct,
    LAG(
      CASE
        WHEN oa_damper_pct IS NOT NULL THEN
          CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct ELSE oa_damper_pct * 100.0 END
        WHEN clg_valve_pct IS NOT NULL THEN
          CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct ELSE clg_valve_pct * 100.0 END
        WHEN htg_valve_pct IS NOT NULL THEN
          CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct ELSE htg_valve_pct * 100.0 END
        WHEN damper_pct IS NOT NULL THEN
          CASE WHEN damper_pct > 1.0 THEN damper_pct ELSE damper_pct * 100.0 END
        ELSE NULL
      END
    ) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_out,
    COALESCE(loop_enabled, 1.0) AS loop_on,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
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
    END AS INT) AS raw_fault
  FROM win
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
