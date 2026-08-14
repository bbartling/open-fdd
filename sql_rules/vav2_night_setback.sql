-- vav2_night_setback.sql — unoccupied zone stays above heating setback
-- Occupied hours do not latch. Missing occ_mode → no unoccupied proof (no fault).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_t,
    occ_mode,
    CAST(CASE
      WHEN occ_mode IS NULL THEN 0
      WHEN LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
        ('unoccupied','unocc','off','false','night','standby','setback','0','0.0','no')
       AND zone_t IS NOT NULL AND zone_t > {{SETBACK_HI}} THEN 1
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
  FROM h
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
