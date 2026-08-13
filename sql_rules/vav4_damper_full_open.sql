-- vav4_damper_full_open.sql — Damper stuck at full open
-- Sustain window (pandas sustain_hours) before counting confirmed hours.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dmp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
cond AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN dmp IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}} AND dmp > {{FULL_OPEN_PCT}} THEN 1
      ELSE 0
    END AS INT) AS cond_fault
  FROM h
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN cond_fault = LAG(cond_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM cond
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
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    -- Only latch after sustain window; then apply confirm streak if larger.
    CAST(CASE
      WHEN cond_fault = 1
       AND streak_len >= CASE
            WHEN {{CONFIRM_ROWS}} > CAST(CEIL({{SUSTAIN_HOURS}} * 3600.0 / {{POLL_SECONDS}}) AS INT)
            THEN {{CONFIRM_ROWS}}
            ELSE CAST(CEIL({{SUSTAIN_HOURS}} * 3600.0 / {{POLL_SECONDS}}) AS INT)
          END
      THEN 1 ELSE 0
    END AS INT) AS raw_fault
  FROM ranked
),
final AS (
  SELECT
    equipment_id,
    raw_fault AS confirmed
  FROM base
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;
