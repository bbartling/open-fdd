-- DuckDB twins of postgres/postgres_helpers.sql (#1645): the fdd.* helpers as SQL macros, SI units only.
-- The DuckDB engine (nf-app/hooks/lib/engines.js, kind "duckdb") installs them once per warm instance and then runs
-- the Postgres rule pack unchanged. Keep each macro equal to its Postgres function; nf-app/tests/duckdb-engine.test.mjs
-- checks them against PGlite on the same inputs.
CREATE SCHEMA IF NOT EXISTS fdd;

-- Postgres trim(value)::double precision, NULL for invalid or out-of-range text.
CREATE OR REPLACE MACRO fdd.try_double(value) AS
  CASE WHEN regexp_full_match(trim(CAST(value AS VARCHAR)), '[+-]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][+-]?[0-9]+)?')
         AND isfinite(TRY_CAST(trim(CAST(value AS VARCHAR)) AS DOUBLE))
       THEN TRY_CAST(trim(CAST(value AS VARCHAR)) AS DOUBLE)
       WHEN regexp_full_match(lower(trim(CAST(value AS VARCHAR))), '[+-]?(inf|infinity|nan)')
       THEN TRY_CAST(trim(CAST(value AS VARCHAR)) AS DOUBLE)
       ELSE NULL END;

CREATE OR REPLACE MACRO fdd.norm_unit(value) AS
  lower(regexp_replace(coalesce(trim(CAST(value AS VARCHAR)), ''), '[^a-zA-Z0-9]', '', 'g'));

CREATE OR REPLACE MACRO fdd.quantity_for_sql_role(role) AS
  CASE
    WHEN trim(role) IN ('air_handling_unit_discharge_air_temperature', 'return_chilled_water_temperature', 'supply_chilled_water_temperature_setpoint', 'supply_chilled_water_temperature',
      'cooling_coil_inlet_air_temperature', 'cooling_coil_outlet_air_temperature', 'zone_cooling_air_temperature_setpoint', 'return_condenser_water_temperature',
      'supply_condenser_water_temperature', 'heating_coil_inlet_air_temperature', 'heating_coil_outlet_air_temperature', 'zone_heating_air_temperature_setpoint',
      'return_hot_water_temperature', 'supply_hot_water_temperature', 'mixed_air_temperature', 'outdoor_air_intake_temperature', 'preheat_heating_coil_outlet_air_temperature', 'return_air_temperature', 'discharge_air_temperature', 'discharge_air_temperature_setpoint',
      'terminal_unit_discharge_air_temperature', 'terminal_unit_inlet_air_temperature', 'weather_service_air_dew_point_temperature', 'weather_service_air_temperature', 'weather_service_air_wet_bulb_temperature', 'zone_air_temperature_setpoint', 'zone_air_temperature')
      THEN 'absolute_temperature'
    WHEN trim(role) IN ('mixed_air_relative_humidity', 'outdoor_air_intake_relative_humidity', 'return_air_relative_humidity', 'discharge_air_relative_humidity', 'weather_service_air_relative_humidity', 'zone_air_relative_humidity')
      THEN 'relative_humidity'
    WHEN trim(role) IN ('chilled_water_pressure_delta', 'chilled_water_pressure_delta_setpoint', 'discharge_air_static_pressure', 'discharge_air_static_pressure_setpoint') THEN 'air_pressure'
    WHEN trim(role) IN ('chilled_water_volume_flow_rate', 'discharge_air_volume_flow_rate_minimum', 'terminal_unit_discharge_air_total_volume_flow_rate', 'discharge_air_volume_flow_rate_setpoint', 'discharge_air_volume_flow_rate') THEN 'volume_flow'
    WHEN trim(role) IN ('chiller_electric_power', 'electric_power') THEN 'power'
    WHEN trim(role) IN ('electric_energy') THEN 'energy'
    WHEN trim(role) IN ('chiller_electric_current') THEN 'electric_current'
    WHEN trim(role) = 'zone_air_co2' THEN 'concentration'
    WHEN trim(role) IN ('chilled_water_reset_request_count', 'hot_water_reset_request_count', 'discharge_air_static_pressure_reset_request_count') THEN 'count'
    ELSE NULL
  END;

CREATE OR REPLACE MACRO fdd.unit_declares_quantity(unit, quantity) AS
  CASE
    WHEN unit IS NULL OR trim(unit) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN fdd.norm_unit(unit) IN ('c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN
      fdd.norm_unit(unit) IN ('pct', 'percent', 'percent0100', 'rh', 'percentrelativehumidity', 'percentrh')
      OR position('%' IN unit) > 0
    WHEN quantity = 'air_pressure' THEN fdd.norm_unit(unit) IN ('pa', 'pascal')
    WHEN quantity = 'volume_flow' THEN fdd.norm_unit(unit) IN ('ls', 'lpersec', 'lsec')
    WHEN quantity = 'power' THEN fdd.norm_unit(unit) = 'kw'
    WHEN quantity = 'energy' THEN fdd.norm_unit(unit) = 'kwh'
    WHEN quantity = 'electric_current' THEN fdd.norm_unit(unit) = 'a'
    WHEN quantity = 'concentration' THEN fdd.norm_unit(unit) = 'ppm'
    WHEN quantity = 'count' THEN fdd.norm_unit(unit) = 'count'
    ELSE false
  END;

CREATE OR REPLACE MACRO fdd.is_expected_constant_sql_role(role) AS
  CASE
    WHEN trim(role) = '' THEN false
    WHEN fdd.norm_unit(role) LIKE '%sp' THEN true
    WHEN position('setpoint' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN position('status' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN fdd.norm_unit(role) LIKE '%cmd' THEN true
    WHEN position('command' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN fdd.norm_unit(role) = 'occmode' THEN true
    WHEN position('occupied' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN position('occupancy' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN fdd.norm_unit(role) = 'loopenabled' THEN true
    ELSE false
  END;

CREATE OR REPLACE MACRO fdd.sweep_assessable_sql_role(role, unit) AS
  CASE
    WHEN fdd.is_expected_constant_sql_role(role) THEN false
    ELSE fdd.unit_declares_quantity(unit, fdd.quantity_for_sql_role(role))
  END;

CREATE OR REPLACE MACRO fdd.mask_sweep_val(role, unit, val) AS
  CASE WHEN fdd.sweep_assessable_sql_role(role, unit) THEN CAST(val AS DOUBLE) ELSE NULL END;

-- Postgres to_char, only the one form the rules use: UTIL-MONTHLY's UTC billing month (ts AT TIME ZONE 'UTC', 'YYYY-MM').
-- Any other format fails loudly instead of returning a wrong key.
CREATE OR REPLACE MACRO to_char(ts, fmt) AS
  CASE WHEN fmt = 'YYYY-MM' THEN strftime(ts, '%Y-%m') ELSE error('to_char: only the YYYY-MM format is supported') END;
