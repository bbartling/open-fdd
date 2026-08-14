-- vav4_damper_full_open.sql — sequential sustain then confirm (pandas vav4).
-- Stage 1: air-on and damper > FULL_OPEN for SUSTAIN_ROWS consecutive samples.
-- Stage 2: confirm that sustained mask for CONFIRM_ROWS (not max of the two).
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
      WHEN zone_flow IS NOT NULL AND zone_flow > {{FLOW_ON_MIN}} THEN 1
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
lagged1 AS (
  SELECT
    *,
    CASE
      WHEN cond_fault = LAG(cond_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new1
  FROM cond
),
grp1 AS (
  SELECT
    *,
    SUM(is_new1) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak1
  FROM lagged1
),
sustained AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN cond_fault = 1
       AND ROW_NUMBER() OVER (PARTITION BY equipment_id, streak1 ORDER BY timestamp_utc)
           >= CAST(CEIL({{SUSTAIN_HOURS}} * 3600.0 / {{POLL_SECONDS}}) AS INT)
      THEN 1 ELSE 0
    END AS INT) AS sustained_fault
  FROM grp1
),
lagged2 AS (
  SELECT
    *,
    CASE
      WHEN sustained_fault = LAG(sustained_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new2
  FROM sustained
),
grp2 AS (
  SELECT
    *,
    SUM(is_new2) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak2
  FROM lagged2
),
final AS (
  SELECT
    equipment_id,
    CAST(CASE
      WHEN sustained_fault = 1
       AND ROW_NUMBER() OVER (PARTITION BY equipment_id, streak2 ORDER BY timestamp_utc) >= {{CONFIRM_ROWS}}
      THEN 1 ELSE 0
    END AS INT) AS confirmed
  FROM grp2
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;
