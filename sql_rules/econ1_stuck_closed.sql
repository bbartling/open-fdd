-- econ1_stuck_closed.sql — ECON-1 economizer stuck closed
-- CAST DOUBLE + percent gate >= 1.5 on damper and fan_cmd (B100 0–100).
-- Pandas _fan is fan-cmd first (percent-normalized), then fan-status (> 0.5).
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN CASE
        WHEN fan_cmd IS NOT NULL THEN CASE
          WHEN (
            CASE
              WHEN CAST(fan_cmd AS DOUBLE) >= 1.5
              THEN CAST(fan_cmd AS DOUBLE) / 100.0
              ELSE CAST(fan_cmd AS DOUBLE)
            END
          ) > 0.01 THEN 1
          ELSE 0
        END
        WHEN fan_status IS NOT NULL THEN CASE WHEN CAST(fan_status AS DOUBLE) > 0.5 THEN 1 ELSE 0 END
        ELSE 0
      END = 0 THEN 0
      WHEN oa_damper_pct IS NOT NULL AND oa_t IS NOT NULL
       AND (
         CASE
           WHEN CAST(oa_damper_pct AS DOUBLE) >= 1.5
           THEN CAST(oa_damper_pct AS DOUBLE) / 100.0
           ELSE CAST(oa_damper_pct AS DOUBLE)
         END
       ) < {{ECON1_DAMPER_MAX}}
       AND CAST(oa_t AS DOUBLE) > {{ECON1_OAT_MIN}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
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
