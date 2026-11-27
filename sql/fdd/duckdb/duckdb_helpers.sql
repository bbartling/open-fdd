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
    WHEN trim(role) IN ('ahu_sat', 'chw_return_t', 'chw_supply_sp', 'chw_supply_t',
      'cooling_coil_entering_temp', 'cooling_coil_leaving_temp', 'cooling_sp', 'cw_return_t',
      'cw_supply_t', 'heating_coil_entering_temp', 'heating_coil_leaving_temp', 'heating_sp',
      'hw_return_t', 'hw_supply_t', 'mat', 'oa_t', 'preheat_leave_t', 'rat', 'sat', 'sat_sp',
      'vav_discharge_t', 'vav_inlet_t', 'web_oa_dp', 'web_oa_t', 'web_wb_t', 'zone_air_temp_sp', 'zone_t')
      THEN 'absolute_temperature'
    WHEN trim(role) IN ('ma_h', 'oa_h', 'ra_h', 'sa_h', 'web_oa_h', 'zone_rh')
      THEN 'relative_humidity'
    WHEN trim(role) IN ('chw_dp', 'chw_dp_sp', 'duct_static', 'duct_static_sp') THEN 'air_pressure'
    WHEN trim(role) IN ('chw_flow', 'min_flow_sp', 'vav_total_flow', 'zone_airflow_sp', 'zone_flow') THEN 'volume_flow'
    WHEN trim(role) IN ('chiller_power', 'electric_kw') THEN 'power'
    WHEN trim(role) IN ('electric_kwh', 'kwh') THEN 'energy'
    WHEN trim(role) IN ('chiller_amps', 'chiller_current') THEN 'electric_current'
    WHEN trim(role) = 'zone_co2' THEN 'concentration'
    WHEN trim(role) IN ('chw_reset_request_sum', 'hw_reset_request_sum', 'static_reset_request') THEN 'count'
    ELSE NULL
  END;

CREATE OR REPLACE MACRO fdd.unit_declares_quantity(unit, quantity) AS
  CASE
    WHEN unit IS NULL OR trim(unit) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN fdd.norm_unit(unit) IN ('c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN
      fdd.norm_unit(unit) IN ('pct', 'percent', 'percent0100', 'rh', 'percentrelativehumidity')
      OR position('%' IN unit) > 0
    WHEN quantity = 'air_pressure' THEN fdd.norm_unit(unit) IN ('pa', 'pascal')
    WHEN quantity = 'volume_flow' THEN fdd.norm_unit(unit) = 'ls'
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
