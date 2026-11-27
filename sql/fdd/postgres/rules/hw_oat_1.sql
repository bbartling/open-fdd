-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- hw_oat_1.sql — Hot-water plant proven on above 18.3 °C web OAT (#1782): the summer-lockout twin of MECH-OAT-1.
-- Proven on, per sample: the hot-water pump status (pump_status > 0.05) or the hot-water supply temperature above the
-- running cut (hw_supply_t > HW_ON_MIN). Neither bound on any sample -> assessment 'no_proof'.
-- Web dry bulb as MECH-OAT-1: the equipment's web_oa_t, else the weather sidecar joined as-of (latest sample at or before
-- the row, at most WEB_ASOF_BOUND_SECONDS old). No outdoor-air sample at all -> assessment 'no_outdoor_air'.
-- Not assessed: fault_hours NULL, covered_hours 0 and no timeline samples (never a silent pass). A sample with no OAT or
-- with neither proof value is unknown: no covered time (fault_pct denominator) and no timeline sample.
-- Fault: proven on while the web dry bulb AT THAT SAMPLE is above HW_OAT_MIN (never a daily maximum, so a cold morning
-- is never a fault), held for CONFIRM_SECONDS (the settle time).
WITH wx_web_oa_t AS (
  SELECT timestamp_utc AS ref_ts, ref_val,
    LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) AS next_ref_ts
  FROM (
    SELECT timestamp_utc, MAX(web_oa_t) AS ref_val
    FROM weather
    WHERE web_oa_t IS NOT NULL
    GROUP BY timestamp_utc
  ) wx_web_oa_t_points
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.web_oa_t, wx_web_oa_t.ref_val) AS web_oa_t,
    CASE WHEN h.pump_status IS NULL THEN NULL WHEN h.pump_status > 0.05 THEN 1 ELSE 0 END AS c1,
    CASE WHEN h.hw_supply_t IS NULL THEN NULL WHEN h.hw_supply_t > {{HW_ON_MIN}} THEN 1 ELSE 0 END AS c2
  FROM history h
  LEFT JOIN wx_web_oa_t
    ON h.timestamp_utc >= wx_web_oa_t.ref_ts
   AND (wx_web_oa_t.next_ref_ts IS NULL OR h.timestamp_utc < wx_web_oa_t.next_ref_ts)
   AND EXTRACT(EPOCH FROM (h.timestamp_utc - wx_web_oa_t.ref_ts)) <= {{WEB_ASOF_BOUND_SECONDS}}
),
inputs AS (
  SELECT equipment_id,
    CASE
      WHEN COUNT(web_oa_t) = 0 THEN 'no_outdoor_air'
      WHEN COUNT(c1) + COUNT(c2) = 0 THEN 'no_proof'
      ELSE 'assessed'
    END AS assessment
  FROM h
  GROUP BY equipment_id
),
base AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    i.assessment,
    CASE WHEN h.web_oa_t IS NOT NULL AND (h.c1 IS NOT NULL OR h.c2 IS NOT NULL) THEN 1 ELSE 0 END AS known,
    CAST(CASE
      WHEN h.web_oa_t IS NULL THEN 0
      WHEN h.web_oa_t <= {{HW_OAT_MIN}} THEN 0
      WHEN h.c1 = 1 OR h.c2 = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
  JOIN inputs i ON i.equipment_id = h.equipment_id
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
    CASE WHEN assessment = 'assessed' AND known = 1 THEN held_seconds ELSE 0.0 END AS held_seconds,
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
