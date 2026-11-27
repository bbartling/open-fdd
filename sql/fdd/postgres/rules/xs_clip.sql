-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- xs_clip.sql — Cross-sensor consistency (#1780): a transmitter clipped at a round full scale (an instrumentation
-- finding, not a range fault: the value may be inside the SV-RANGE bounds).
-- Roles and their round step (SI): zone_air_co2 (CO2_ROUND ppm), discharge_air_static_pressure (STATIC_ROUND Pa), discharge_air_volume_flow_rate (FLOW_ROUND L/s).
-- discharge_air_static_pressure and discharge_air_volume_flow_rate count only fan-on samples (supply_fan_operating_status, else supply_fan_command, else operating_status, else every sample).
-- A role is clipped when its highest counted value is a positive multiple of its round step, at least CLIP_SHARE
-- percent of its counted samples sit at that value (within 1e-6; CLIP_SHARE is 0-100, QUDT PERCENT), and the series
-- is not flat (some sample is lower). A design maximum
-- that is not round, or reached once, is not clipped.
-- Fault: a counted sample of a clipped role at the clip value, held for CONFIRM_SECONDS. No role with data ->
-- assessment 'no_clip_role': fault_hours NULL, covered_hours 0 (never a silent pass).
WITH v AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_air_co2 AS v1,
    CASE WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN discharge_air_static_pressure END
         WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > {{FAN_ON_MIN}} THEN discharge_air_static_pressure END
         WHEN operating_status IS NOT NULL THEN CASE WHEN operating_status > 0.05 THEN discharge_air_static_pressure END
         ELSE discharge_air_static_pressure END AS v2,
    CASE WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN discharge_air_volume_flow_rate END
         WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > {{FAN_ON_MIN}} THEN discharge_air_volume_flow_rate END
         WHEN operating_status IS NOT NULL THEN CASE WHEN operating_status > 0.05 THEN discharge_air_volume_flow_rate END
         ELSE discharge_air_volume_flow_rate END AS v3,
    CASE WHEN zone_air_co2 IS NULL AND discharge_air_static_pressure IS NULL AND discharge_air_volume_flow_rate IS NULL THEN 0 ELSE 1 END AS has_role
  FROM history
),
tops AS (
  SELECT equipment_id,
    MAX(v1) AS t1, MIN(v1) AS l1, COUNT(v1) AS c1,
    MAX(v2) AS t2, MIN(v2) AS l2, COUNT(v2) AS c2,
    MAX(v3) AS t3, MIN(v3) AS l3, COUNT(v3) AS c3,
    CASE WHEN SUM(has_role) = 0 THEN 'no_clip_role' ELSE 'assessed' END AS assessment
  FROM v
  GROUP BY equipment_id
),
at_top AS (
  SELECT v.equipment_id, v.timestamp_utc,
    CASE WHEN v.v1 IS NOT NULL AND v.v1 >= t.t1 - 0.000001 THEN 1 ELSE 0 END AS a1,
    CASE WHEN v.v2 IS NOT NULL AND v.v2 >= t.t2 - 0.000001 THEN 1 ELSE 0 END AS a2,
    CASE WHEN v.v3 IS NOT NULL AND v.v3 >= t.t3 - 0.000001 THEN 1 ELSE 0 END AS a3
  FROM v
  JOIN tops t ON t.equipment_id = v.equipment_id
),
clipped AS (
  SELECT t.equipment_id, t.assessment,
    CASE WHEN t.t1 > 0 AND t.l1 < t.t1 - 0.000001
          AND ABS(t.t1 - {{CO2_ROUND}} * ROUND(t.t1 / {{CO2_ROUND}})) <= 0.000001
          AND 100.0 * SUM(a.a1) >= {{CLIP_SHARE}} * t.c1 THEN 1 ELSE 0 END AS k1,
    CASE WHEN t.t2 > 0 AND t.l2 < t.t2 - 0.000001
          AND ABS(t.t2 - {{STATIC_ROUND}} * ROUND(t.t2 / {{STATIC_ROUND}})) <= 0.000001
          AND 100.0 * SUM(a.a2) >= {{CLIP_SHARE}} * t.c2 THEN 1 ELSE 0 END AS k2,
    CASE WHEN t.t3 > 0 AND t.l3 < t.t3 - 0.000001
          AND ABS(t.t3 - {{FLOW_ROUND}} * ROUND(t.t3 / {{FLOW_ROUND}})) <= 0.000001
          AND 100.0 * SUM(a.a3) >= {{CLIP_SHARE}} * t.c3 THEN 1 ELSE 0 END AS k3
  FROM tops t
  JOIN at_top a ON a.equipment_id = t.equipment_id
  GROUP BY t.equipment_id, t.assessment, t.t1, t.l1, t.c1, t.t2, t.l2, t.c2, t.t3, t.l3, t.c3
),
base AS (
  SELECT
    a.equipment_id,
    a.timestamp_utc,
    k.assessment,
    CAST(CASE
      WHEN k.k1 = 1 AND a.a1 = 1 THEN 1
      WHEN k.k2 = 1 AND a.a2 = 1 THEN 1
      WHEN k.k3 = 1 AND a.a3 = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM at_top a
  JOIN clipped k ON k.equipment_id = a.equipment_id
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
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
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
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
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    assessment,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  CASE WHEN MAX(assessment) = 'assessed'
       THEN SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 ELSE NULL END AS fault_hours,
  CASE WHEN MAX(assessment) = 'assessed' THEN SUM(held_seconds) / 3600.0 ELSE 0.0 END AS covered_hours,
  CASE WHEN MAX(assessment) = 'assessed'
       THEN 100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0)
       ELSE NULL END AS fault_pct,
  MAX(assessment) AS assessment
FROM final
GROUP BY equipment_id;
