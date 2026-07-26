-- econ5_preheat_over.sql — Preheat over-conditioning (matches vibe19 econ5)
-- Target = OAT when OAT > SAT SP; else SAT SP. Fault when preheat exceeds target by ΔT
-- while heating valve is open.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    preheat_leave_t, sat_sp, oa_t,
    CASE WHEN htg_valve_pct IS NULL THEN 0.0 WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN preheat_leave_t IS NULL OR sat_sp IS NULL OR oa_t IS NULL THEN 0
      WHEN htg > 0.01 AND (
        (oa_t > sat_sp AND preheat_leave_t - oa_t > {{PREHEAT_OVER_F}})
        OR (oa_t < sat_sp AND preheat_leave_t - sat_sp > {{PREHEAT_OVER_F}})
      ) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
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
