-- sched247_always_on.sql — Always-on fan or pump runtime
-- Pandas `_sched247`: ranked proof (status > command), then FAULT only when
-- mean(on) >= always_on_pct over the whole analysis window. Confirmed hours
-- are the on-mask after that gate (not a streak-only screen).
-- Pressure is not used for the FAULT mask (4.3 migration).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    fan_status,
    pump_status,
    chiller_status,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan IS NOT NULL THEN CASE WHEN fan >= 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS INT) AS on_bit
  FROM h
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    on_bit,
    AVG(CAST(on_bit AS DOUBLE)) OVER (PARTITION BY equipment_id) AS on_frac
  FROM proof
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN on_frac >= {{ALWAYS_ON_PCT}} AND on_bit = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
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
