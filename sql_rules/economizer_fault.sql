-- economizer_fault.sql — ECON-2 economizing when outdoor unfavorable + confirm
-- Damper is damper_frac (never aliased back to oa_damper_pct — DataFusion can
-- keep the raw same-name column in later CTEs, so 20 > 0.42 would still fire).
-- Pandas econ2 has no fan gate: OAT > ECON2_OAT_HI AND damper_frac > ECON2_DAMPER.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    CASE
      WHEN oa_damper_pct IS NULL THEN NULL
      WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0
      ELSE oa_damper_pct
    END AS damper_frac
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND damper_frac IS NOT NULL
       AND oa_t > {{ECON2_OAT_HI}} AND damper_frac > {{ECON2_DAMPER}}
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
