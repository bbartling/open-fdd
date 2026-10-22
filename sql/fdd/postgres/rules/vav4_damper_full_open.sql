-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav4_damper_full_open.sql — sequential sustain then confirm (pandas vav4).
-- Stage 1: air-on and damper > FULL_OPEN for SUSTAIN_HOURS of eligible elapsed time.
-- Stage 2: confirm that sustained mask for CONFIRM_SECONDS (not the max of the two).
-- Gaps longer than MAX_GAP_HOURS are unknown and break both streaks.
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
elapsed_hold AS (
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM cond src
  ) stepped
),
lagged1 AS (
  SELECT
    *,
    CASE
      WHEN cond_fault = LAG(cond_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new1
  FROM elapsed_hold
),
grp1 AS (
  SELECT
    *,
    SUM(is_new1) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak1
  FROM lagged1
),
sustained AS (
  SELECT
    *,
    CAST(CASE
      WHEN cond_fault = 1
       AND SUM(held_seconds) OVER (
         PARTITION BY equipment_id, streak1 ORDER BY timestamp_utc
         ROWS UNBOUNDED PRECEDING
       ) >= ({{SUSTAIN_HOURS}} * 3600.0)
      THEN 1 ELSE 0
    END AS INT) AS sustained_fault
  FROM grp1
),
lagged2 AS (
  SELECT
    *,
    CASE
      WHEN sustained_fault = LAG(sustained_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
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
    held_seconds,
    CAST(CASE
      WHEN sustained_fault = 1
       AND SUM(held_seconds) OVER (
         PARTITION BY equipment_id, streak2 ORDER BY timestamp_utc
         ROWS UNBOUNDED PRECEDING
       ) >= {{CONFIRM_SECONDS}}
      THEN 1 ELSE 0
    END AS INT) AS confirmed
  FROM grp2
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
