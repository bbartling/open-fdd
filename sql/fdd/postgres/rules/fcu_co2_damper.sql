-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_co2_damper.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, discharge_air_temperature, zone_air_temperature, zone_air_co2,
    heating_valve_position_command AS htg,
    cooling_valve_position_command AS clg,
    damper_position_command AS dcmd,
    damper_position AS dpos,
    CASE
      WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN 1 ELSE 0 END
      WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > 0.5 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN fan_on = 1 AND zone_air_co2 IS NOT NULL AND zone_air_co2 > {{CO2_HIGH_PPM}} AND zone_air_co2 >= 300.0 AND dcmd IS NOT NULL AND dcmd < {{DAMPER_LOW}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
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
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
