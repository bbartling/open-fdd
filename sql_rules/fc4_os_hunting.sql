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
    END AS fan
  FROM history
),
modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    DATE_TRUNC('hour', timestamp_utc) AS clock_hour,
    CASE
      WHEN fan IS NULL OR fan < 0.05 THEN 0
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
