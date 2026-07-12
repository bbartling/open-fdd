-- vav4_damper_full_open.sql — VAV-4 damper stuck at full open + confirm
WITH h AS (
  SELECT * FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END, 0.0) IS NOT NULL AND zone_flow IS NOT NULL
        AND zone_flow > {{FLOW_ON_MIN}}
        AND COALESCE(CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END, 0.0) > {{FULL_OPEN_PCT}}
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
