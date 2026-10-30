-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sched1_unoccupied_runtime.sql — Excess / wasted unoccupied runtime
-- Storage is SI (metric-c-v2): zone_t and the ZONE_T_LO / ZONE_T_HI comfort band are °C.
-- Pandas sched1: unoccupied & fan_on; when zone_t mapped, also require comfort band
-- (zone already satisfied → optimal-start / bad schedule signal).
-- When zone_t is absent from history, the runner injects NULL zone_t (optional role)
-- so behavior matches pandas “no zone → base only”.
-- Portable occupancy: literal 'unoccupied' OR numeric/boolean falsey (0 / 0.0 / false).
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
        CAST(CASE
          WHEN occ_mode IS NULL OR fan_status IS NULL THEN 0
          WHEN fan_status > 0.5
            AND (
              LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
                ('unoccupied','unocc','off','false','night','standby','setback','no')
              OR (
                fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
                AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
              )
            )
            AND (
              zone_t IS NULL
              OR (zone_t >= {{ZONE_T_LO}} AND zone_t <= {{ZONE_T_HI}})
            )
          THEN 1
          ELSE 0
        END AS INT) AS raw_fault
  FROM history
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
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
