-- pid_hunt_1.sql — Suspected control-output hunting
-- Simplified SQL variant. Full rolling TV/cycle/reversal logic validated in Pandas.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN clg_valve_pct IS NULL THEN NULL
         WHEN clg_valve_pct > 1.0 THEN clg_valve_pct
         ELSE clg_valve_pct * 100.0 END AS out_pct,
    LAG(CASE WHEN clg_valve_pct IS NULL THEN NULL
             WHEN clg_valve_pct > 1.0 THEN clg_valve_pct
             ELSE clg_valve_pct * 100.0 END)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_out
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN out_pct IS NULL OR prev_out IS NULL THEN 0
      WHEN ABS(out_pct - prev_out) > {{CHANGE_DEADBAND_PCT}}
       AND ABS(out_pct - prev_out) >= {{MINIMUM_SPAN_PCT}} / 10.0
      THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
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
