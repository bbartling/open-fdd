-- pid_hunt_1.sql — PID-HUNT-1 suspected control-output hunting (rolling window)
-- Placeholders: POLL_SECONDS, WINDOW_ROWS, WINDOW_ROWS_MINUS_ONE, CONFIRM_ROWS,
-- CHANGE_DEADBAND_PCT, MINIMUM_SPAN_PCT, TOTAL_VARIATION_FAULT_PCT,
-- MINIMUM_EQUIVALENT_CYCLES, MINIMUM_REVERSALS, MINIMUM_COVERAGE_PCT,
-- MINIMUM_SAMPLES, WINDOW_MINUTES
--
-- WINDOW_ROWS is derived at runtime from WINDOW_MINUTES and POLL_SECONDS
-- (ceil(window_minutes * 60 / poll_seconds), minimum 2).
--
-- Input roles: control_output_pct (required), loop_enabled (optional).
-- Optional-role policy: when loop_enabled is projected as a column, NULL cells
-- count as disabled (fillna(0) parity with Pandas/Vibe19). When the role is
-- absent, the projection layer should inject TRUE (no enable restriction).
--
-- Output: equipment-level fault_hours only. Status mapping (PASS/FAULT/
-- SKIPPED_*) is applied by the rule runner / API layer, not this SQL file.
-- UI wording: "Suspected control-loop hunting" — output travel ≠ bad PID alone.
WITH params AS (
  SELECT
    CAST({{CHANGE_DEADBAND_PCT}} AS DOUBLE) AS change_deadband_pct,
    CAST({{MINIMUM_SPAN_PCT}} AS DOUBLE) AS minimum_span_pct,
    CAST({{TOTAL_VARIATION_FAULT_PCT}} AS DOUBLE) AS total_variation_fault_pct,
    CAST({{MINIMUM_EQUIVALENT_CYCLES}} AS DOUBLE) AS minimum_equivalent_cycles,
    CAST({{MINIMUM_REVERSALS}} AS BIGINT) AS minimum_reversals,
    CAST({{MINIMUM_COVERAGE_PCT}} AS DOUBLE) AS minimum_coverage_pct,
    CAST({{MINIMUM_SAMPLES}} AS BIGINT) AS minimum_samples
),
norm AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN control_output_pct IS NULL THEN NULL
      WHEN control_output_pct > 1.5 THEN
        CASE
          WHEN control_output_pct < 0.0 THEN 0.0
          WHEN control_output_pct > 100.0 THEN 100.0
          ELSE control_output_pct
        END
      ELSE
        CASE
          WHEN control_output_pct * 100.0 < 0.0 THEN 0.0
          WHEN control_output_pct * 100.0 > 100.0 THEN 100.0
          ELSE control_output_pct * 100.0
        END
    END AS control_output_pct,
    -- Present-but-null → disabled (Pandas fillna(0).gt(0) / Vibe19).
    COALESCE(CAST(loop_enabled AS DOUBLE) > 0.0, FALSE) AS loop_enabled
  FROM history
),
ordered AS (
  SELECT
    n.*,
    LAG(control_output_pct, 1) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
    ) AS previous_output_pct
  FROM norm n
  WHERE control_output_pct IS NOT NULL
),
deltas AS (
  SELECT
    o.*,
    CASE
      WHEN previous_output_pct IS NULL THEN 0.0
      WHEN ABS(control_output_pct - previous_output_pct) < p.change_deadband_pct THEN 0.0
      ELSE control_output_pct - previous_output_pct
    END AS significant_delta,
    CASE
      WHEN previous_output_pct IS NULL THEN 0
      WHEN control_output_pct - previous_output_pct >= p.change_deadband_pct THEN 1
      WHEN control_output_pct - previous_output_pct <= -p.change_deadband_pct THEN -1
      ELSE 0
    END AS direction
  FROM ordered o
  CROSS JOIN params p
),
-- Carry forward last significant direction (+1/-1) across deadband/flat rows
-- so sequences like +1, 0, -1 count as one reversal (Pandas ffill semantics).
directions AS (
  SELECT
    d.*,
    LAST_VALUE(
      CASE WHEN direction <> 0 THEN direction END
    ) IGNORE NULLS OVER (
      PARTITION BY equipment_id
      ORDER BY timestamp_utc
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS significant_direction
  FROM deltas d
),
with_prev AS (
  SELECT
    d.*,
    LAG(significant_direction, 1) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
    ) AS previous_significant_direction
  FROM directions d
),
rolling_metrics AS (
  SELECT
    timestamp_utc,
    equipment_id,
    control_output_pct,
    loop_enabled,
    COUNT(control_output_pct) OVER output_window AS sample_count,
    SUM(ABS(significant_delta)) OVER output_window AS total_variation_1h,
    MIN(control_output_pct) OVER output_window AS output_min_1h,
    MAX(control_output_pct) OVER output_window AS output_max_1h,
    SUM(
      CASE
        WHEN significant_direction IS NOT NULL
         AND previous_significant_direction IS NOT NULL
         AND significant_direction <> previous_significant_direction
        THEN 1 ELSE 0
      END
    ) OVER output_window AS reversals_1h
  FROM with_prev
  WINDOW output_window AS (
    PARTITION BY equipment_id
    ORDER BY timestamp_utc
    ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW
  )
),
scored AS (
  SELECT
    r.*,
    p.minimum_samples,
    p.minimum_span_pct,
    p.total_variation_fault_pct,
    p.minimum_equivalent_cycles,
    p.minimum_reversals,
    p.minimum_coverage_pct,
    (output_max_1h - output_min_1h) AS output_span_1h,
    100.0 * CAST(sample_count AS DOUBLE) / CAST({{WINDOW_ROWS}} AS DOUBLE) AS coverage_pct_1h,
    CASE
      WHEN (output_max_1h - output_min_1h) > 0.0
      THEN total_variation_1h / (2.0 * (output_max_1h - output_min_1h))
      ELSE 0.0
    END AS equivalent_cycles_1h,
    CAST(
      CASE
        WHEN sample_count < p.minimum_samples THEN 0
        WHEN NOT loop_enabled THEN 0
        WHEN (100.0 * CAST(sample_count AS DOUBLE) / CAST({{WINDOW_ROWS}} AS DOUBLE))
             < p.minimum_coverage_pct THEN 0
        WHEN (output_max_1h - output_min_1h) >= p.minimum_span_pct
         AND total_variation_1h >= p.total_variation_fault_pct
         AND (
           CASE
             WHEN (output_max_1h - output_min_1h) > 0.0
             THEN total_variation_1h / (2.0 * (output_max_1h - output_min_1h))
             ELSE 0.0
           END
         ) >= p.minimum_equivalent_cycles
         AND reversals_1h >= p.minimum_reversals
        THEN 1
        ELSE 0
      END AS INT
    ) AS raw_fault
  FROM rolling_metrics r
  CROSS JOIN params p
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM scored
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
