-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- coil_perf.sql — Generic coil performance (#1641): a heating or cooling coil commanded open does not change the air
-- temperature by MIN_DT. One rule for any coil-bearing equipment, applied by bound roles (never by equipment names).
--
-- Mode per sample:
--   heating: heating valve (heating_valve_position_command, else terminal_unit_heating_valve_position_command) >= VALVE_OPEN and the cooling valve, if bound, <= VALVE_SHUT
--   cooling: cooling valve >= VALVE_OPEN and the heating / reheat valves, if bound, <= VALVE_SHUT
-- Temperature pair, the first complete one in this order (entering -> leaving):
--   1. dedicated coil sensors (heating_coil_inlet_air_temperature / _leaving_temp, cooling_coil_inlet_air_temperature / _leaving_temp)
--   2. air handler: mixed_air_temperature -> discharge_air_temperature
--   3. VAV reheat: terminal_unit_inlet_air_temperature -> terminal_unit_discharge_air_temperature
--   4. fan coil / zone: zone_air_temperature -> discharge_air_temperature
-- Fault: heating and (leave - enter) < MIN_DT, or cooling and (enter - leave) < MIN_DT, with the fan on (supply_fan_operating_status, else
-- supply_fan_command) and, where discharge_air_volume_flow_rate is bound, airflow above FLOW_ON_MIN.
-- No coil valve or no temperature pair on any sample -> assessment 'no_coil_valve' / 'no_temperature_pair':
-- fault_hours NULL, covered_hours 0 (never a silent pass). Run-proof gated like the other air-side rules (#1608).
WITH rp AS (
  -- Run proof (#1608): the input role operating_status is resolved from the model (own status, own command, feeding equipment).
  -- With the gate on and no proof bound at all, the equipment is SKIPPED: fault_hours NULL, covered_hours 0.
  SELECT equipment_id,
    CASE WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COUNT(operating_status) = 0 THEN 1 ELSE 0 END AS no_run_proof
  FROM history
  GROUP BY equipment_id
),
h AS (
  SELECT
    operating_status,
    equipment_id,
    timestamp_utc,
    COALESCE(heating_valve_position_command, terminal_unit_heating_valve_position_command) AS htg,
    cooling_valve_position_command AS clg,
    heating_valve_position_command,
    terminal_unit_heating_valve_position_command,
    discharge_air_volume_flow_rate,
    CASE
      WHEN supply_fan_operating_status IS NOT NULL THEN CASE WHEN supply_fan_operating_status > 0.05 THEN 1 ELSE 0 END
      WHEN supply_fan_command IS NOT NULL THEN CASE WHEN supply_fan_command > 0.5 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on,
    CASE
      WHEN heating_coil_outlet_air_temperature IS NOT NULL AND heating_coil_inlet_air_temperature IS NOT NULL THEN heating_coil_outlet_air_temperature - heating_coil_inlet_air_temperature
      WHEN discharge_air_temperature IS NOT NULL AND mixed_air_temperature IS NOT NULL THEN discharge_air_temperature - mixed_air_temperature
      WHEN terminal_unit_discharge_air_temperature IS NOT NULL AND terminal_unit_inlet_air_temperature IS NOT NULL THEN terminal_unit_discharge_air_temperature - terminal_unit_inlet_air_temperature
      WHEN discharge_air_temperature IS NOT NULL AND zone_air_temperature IS NOT NULL THEN discharge_air_temperature - zone_air_temperature
      ELSE NULL
    END AS heat_rise,
    CASE
      WHEN cooling_coil_outlet_air_temperature IS NOT NULL AND cooling_coil_inlet_air_temperature IS NOT NULL THEN cooling_coil_inlet_air_temperature - cooling_coil_outlet_air_temperature
      WHEN discharge_air_temperature IS NOT NULL AND mixed_air_temperature IS NOT NULL THEN mixed_air_temperature - discharge_air_temperature
      WHEN terminal_unit_discharge_air_temperature IS NOT NULL AND terminal_unit_inlet_air_temperature IS NOT NULL THEN terminal_unit_inlet_air_temperature - terminal_unit_discharge_air_temperature
      WHEN discharge_air_temperature IS NOT NULL AND zone_air_temperature IS NOT NULL THEN zone_air_temperature - discharge_air_temperature
      ELSE NULL
    END AS cool_drop
  FROM history
),
pairs AS (
  -- not assessable: no coil valve with data, or no complete temperature pair (reported, never a silent pass)
  SELECT equipment_id,
    CASE WHEN COUNT(htg) + COUNT(clg) = 0 OR COUNT(heat_rise) + COUNT(cool_drop) = 0 THEN 1 ELSE 0 END AS no_pair,
    CASE WHEN COUNT(htg) + COUNT(clg) = 0 THEN 'no_coil_valve'
         WHEN COUNT(heat_rise) + COUNT(cool_drop) = 0 THEN 'no_temperature_pair'
         ELSE 'assessed' END AS assessment
  FROM h
  GROUP BY equipment_id
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(operating_status, 0) <= 0.05 THEN 0
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN discharge_air_volume_flow_rate IS NOT NULL AND discharge_air_volume_flow_rate <= {{FLOW_ON_MIN}} THEN 0
      WHEN htg IS NOT NULL AND htg >= {{VALVE_OPEN}} AND (clg IS NULL OR clg <= {{VALVE_SHUT}})
       AND heat_rise IS NOT NULL AND heat_rise < {{MIN_DT}} THEN 1
      WHEN clg IS NOT NULL AND clg >= {{VALVE_OPEN}}
       AND (heating_valve_position_command IS NULL OR heating_valve_position_command <= {{VALVE_SHUT}})
       AND (terminal_unit_heating_valve_position_command IS NULL OR terminal_unit_heating_valve_position_command <= {{VALVE_SHUT}})
       AND cool_drop IS NOT NULL AND cool_drop < {{MIN_DT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN operating_status > 0.05 THEN 1 ELSE 0 END AS proof_active
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
    proof_active,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT px.no_pair FROM pairs px WHERE px.equipment_id = final.equipment_id) = 1 THEN NULL
       ELSE SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS fault_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT px.no_pair FROM pairs px WHERE px.equipment_id = final.equipment_id) = 1 THEN 0.0
       ELSE SUM(held_seconds) / 3600.0 END AS covered_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT px.no_pair FROM pairs px WHERE px.equipment_id = final.equipment_id) = 1 THEN 0.0
       ELSE SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS active_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1
         OR (SELECT px.no_pair FROM pairs px WHERE px.equipment_id = final.equipment_id) = 1 THEN NULL
       ELSE COALESCE(100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END)
                     / NULLIF(SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END), 0.0), 0.0) END AS fault_pct,
  (SELECT px.assessment FROM pairs px WHERE px.equipment_id = final.equipment_id) AS assessment
FROM final
GROUP BY equipment_id;
