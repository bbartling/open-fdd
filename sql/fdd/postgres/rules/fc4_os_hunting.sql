-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc4_os_hunting.sql — PID hunting (operating-state oscillation), GL36 fault 4
-- ΔOS > ΔOSmax during the clock hour: count how many times the AHU *enters* each
-- operating state within the hour and flag the whole hour when any state is
-- entered more than DELTA_OS_MAX times.
-- Operating states: 1 = min OA / heating, 2 = economizer, 3 = mechanical cooling
-- (0 = fan off, not counted).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
      WHEN fan_cmd IS NULL THEN NULL
      WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0
      ELSE fan_cmd
    END AS fan,
    CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    DATE_TRUNC('hour', timestamp_utc) AS clock_hour,
    CASE
      WHEN fan IS NULL OR fan < {{FAN_ON_MIN}} THEN 0
      WHEN clg IS NOT NULL AND clg > 0.1 THEN 3
      WHEN oa_d IS NOT NULL AND oa_d > 0.5 THEN 2
      ELSE 1
    END AS op_mode
  FROM h
),
entries AS (
  SELECT
    equipment_id,
    timestamp_utc,
    clock_hour,
    op_mode,
    CASE
      WHEN op_mode = 0 THEN 0
      WHEN LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN op_mode <> LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 1
      ELSE 0
    END AS is_entry
  FROM modes
),
hourly AS (
  SELECT
    equipment_id,
    timestamp_utc,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 1 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_min_oa,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 2 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_econ,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 3 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_mech
  FROM entries
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN entries_min_oa > {{DELTA_OS_MAX}} THEN 1
      WHEN entries_econ > {{DELTA_OS_MAX}} THEN 1
      WHEN entries_mech > {{DELTA_OS_MAX}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM hourly
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
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
