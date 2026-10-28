-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav1_comfort_fault.sql — zone comfort band with confirm window (Open-FDD parity)
-- When occ_mode is present, require_occupied (default 1) scores the band only
-- while occupied. The rule runner synthesizes occ_mode from the saved Overview
-- calendar (session occupancy_schedule) when no modeled occ_mode exists.
-- With neither signal, the product path reports NOT_ASSESSED_NO_OCCUPANCY (0 fault
-- seconds). Unoccupied setback stays on VAV-2.
-- OFDD-065: do not reference fan_cmd here. Zone-only parquet schemas
-- often lack fan_cmd; DataFusion then schema-errors → SKIPPED_MISSING_ROLES.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_t,
    occ_mode,
    CAST(CASE WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN 1 ELSE 0 END AS INT) AS band_fault
  FROM history
  WHERE zone_t IS NOT NULL
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_OCCUPIED}} >= 0.5
       AND occ_mode IS NOT NULL
       AND (
         LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
           ('unoccupied','unocc','off','false','night','standby','setback','no')
         OR (
           fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
           AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
         )
       )
      THEN 0
      ELSE band_fault
    END AS INT) AS raw_fault
  FROM h
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
    timestamp_utc,
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
