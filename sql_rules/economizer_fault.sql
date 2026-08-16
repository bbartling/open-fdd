-- economizer_fault.sql — ECON-2 economizing when outdoor unfavorable + confirm
-- CAST DOUBLE + percent gate >= 1.5 (not > 1.0) so Utf8/int 0–100 (B100 min OA 20)
-- becomes 0.20 and does not fire vs ECON2_DAMPER 0.42. Fraction 0–1 stays 0–1.
-- Pandas econ2 has no fan gate.
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND oa_damper_pct IS NOT NULL
       AND CAST(oa_t AS DOUBLE) > {{ECON2_OAT_HI}}
       AND (
         CASE
           WHEN CAST(oa_damper_pct AS DOUBLE) >= 1.5
           THEN CAST(oa_damper_pct AS DOUBLE) / 100.0
           ELSE CAST(oa_damper_pct AS DOUBLE)
         END
       ) > {{ECON2_DAMPER}}
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
