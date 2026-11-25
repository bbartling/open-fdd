-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- xs_copy.sql — Cross-sensor consistency (#1780): two temperature roles of one unit carry the same (copied) signal.
-- Pairs: rat/sat, mat/sat, mat/rat, zone_t/sat, zone_t/vav_discharge_t. A pair matches at a sample when both are bound
-- and |a - b| <= COPY_TOL. A run of consecutive matching samples is a copy when the first role moves by at least
-- CHANGE_MIN over the run (max - min): two flat series that agree are a flatline (SV-FLATLINE), not a copy.
-- Fault: any pair in a copy run, held for CONFIRM_SECONDS (hours, not a few samples). Both roles are named; blame is
-- not assigned. No pair with both roles on any sample -> assessment 'no_pair': fault_hours NULL, covered_hours 0.
WITH m AS (
  SELECT
    equipment_id,
    timestamp_utc,
    rat, mat, zone_t,
    CASE WHEN rat IS NOT NULL AND sat IS NOT NULL THEN CASE WHEN ABS(rat - sat) <= {{COPY_TOL}} THEN 1 ELSE 0 END END AS m1,
    CASE WHEN mat IS NOT NULL AND sat IS NOT NULL THEN CASE WHEN ABS(mat - sat) <= {{COPY_TOL}} THEN 1 ELSE 0 END END AS m2,
    CASE WHEN mat IS NOT NULL AND rat IS NOT NULL THEN CASE WHEN ABS(mat - rat) <= {{COPY_TOL}} THEN 1 ELSE 0 END END AS m3,
    CASE WHEN zone_t IS NOT NULL AND sat IS NOT NULL THEN CASE WHEN ABS(zone_t - sat) <= {{COPY_TOL}} THEN 1 ELSE 0 END END AS m4,
    CASE WHEN zone_t IS NOT NULL AND vav_discharge_t IS NOT NULL
         THEN CASE WHEN ABS(zone_t - vav_discharge_t) <= {{COPY_TOL}} THEN 1 ELSE 0 END END AS m5
  FROM history
),
inputs AS (
  SELECT equipment_id,
    CASE WHEN COUNT(m1) + COUNT(m2) + COUNT(m3) + COUNT(m4) + COUNT(m5) = 0 THEN 'no_pair' ELSE 'assessed' END AS assessment
  FROM m
  GROUP BY equipment_id
),
edges AS (
  -- a new run starts wherever the match flag changes (a missing pair is not a match)
  SELECT m.*,
    CASE WHEN COALESCE(m1, 0) = COALESCE(LAG(m1) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) THEN 0 ELSE 1 END AS n1,
    CASE WHEN COALESCE(m2, 0) = COALESCE(LAG(m2) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) THEN 0 ELSE 1 END AS n2,
    CASE WHEN COALESCE(m3, 0) = COALESCE(LAG(m3) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) THEN 0 ELSE 1 END AS n3,
    CASE WHEN COALESCE(m4, 0) = COALESCE(LAG(m4) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) THEN 0 ELSE 1 END AS n4,
    CASE WHEN COALESCE(m5, 0) = COALESCE(LAG(m5) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) THEN 0 ELSE 1 END AS n5
  FROM m
),
runs AS (
  SELECT edges.*,
    SUM(n1) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS r1,
    SUM(n2) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS r2,
    SUM(n3) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS r3,
    SUM(n4) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS r4,
    SUM(n5) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS r5
  FROM edges
),
spans AS (
  SELECT runs.*,
    MAX(rat) OVER (PARTITION BY equipment_id, r1) - MIN(rat) OVER (PARTITION BY equipment_id, r1) AS s1,
    MAX(mat) OVER (PARTITION BY equipment_id, r2) - MIN(mat) OVER (PARTITION BY equipment_id, r2) AS s2,
    MAX(mat) OVER (PARTITION BY equipment_id, r3) - MIN(mat) OVER (PARTITION BY equipment_id, r3) AS s3,
    MAX(zone_t) OVER (PARTITION BY equipment_id, r4) - MIN(zone_t) OVER (PARTITION BY equipment_id, r4) AS s4,
    MAX(zone_t) OVER (PARTITION BY equipment_id, r5) - MIN(zone_t) OVER (PARTITION BY equipment_id, r5) AS s5
  FROM runs
),
base AS (
  SELECT
    s.equipment_id,
    s.timestamp_utc,
    i.assessment,
    CAST(CASE
      WHEN s.m1 = 1 AND s.s1 >= {{CHANGE_MIN}} THEN 1
      WHEN s.m2 = 1 AND s.s2 >= {{CHANGE_MIN}} THEN 1
      WHEN s.m3 = 1 AND s.s3 >= {{CHANGE_MIN}} THEN 1
      WHEN s.m4 = 1 AND s.s4 >= {{CHANGE_MIN}} THEN 1
      WHEN s.m5 = 1 AND s.s5 >= {{CHANGE_MIN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM spans s
  JOIN inputs i ON i.equipment_id = s.equipment_id
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
