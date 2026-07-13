-- cmd1_fan_mismatch.sql — CMD-1 fan command vs status mismatch + confirm
WITH h AS (
  SELECT
    *,
    CASE
      WHEN fan_cmd IS NULL THEN NULL
      WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0
      ELSE fan_cmd
    END AS fan_cmd_norm,
    CASE
      WHEN fan_status IS NULL THEN NULL
      WHEN TRIM(CAST(fan_status AS VARCHAR)) IN ('1', '1.0', 'true', 'TRUE', 'on', 'ON', 'yes', 'YES') THEN TRUE
      ELSE FALSE
    END AS fan_status_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN fan_cmd_norm IS NOT NULL AND fan_status_on IS NOT NULL
        AND ((fan_cmd_norm >= 0.05) <> fan_status_on)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
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
