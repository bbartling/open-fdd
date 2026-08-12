-- sched1_unoccupied_runtime.sql — Excess / wasted unoccupied runtime
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
                try_cast(trim(CAST(occ_mode AS VARCHAR)) AS DOUBLE) IS NOT NULL
                AND try_cast(trim(CAST(occ_mode AS VARCHAR)) AS DOUBLE) <= 0.05
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
