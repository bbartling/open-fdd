-- DuckDB twins of sql/fdd/postgres/postgres_helpers.sql (plpgsql does not parse in DuckDB): narrowly scoped
-- fdd.* scalar macros used by the occupancy and sensor-sweep rules. Run once per connection, with SET TimeZone = 'UTC'.
CREATE SCHEMA IF NOT EXISTS fdd;

CREATE OR REPLACE MACRO fdd.try_double(v) AS (
  CASE
    WHEN ISFINITE(TRY_CAST(NULLIF(TRIM(CAST(v AS VARCHAR)), '') AS DOUBLE))
      THEN TRY_CAST(NULLIF(TRIM(CAST(v AS VARCHAR)), '') AS DOUBLE)
    ELSE NULL
  END
);

CREATE OR REPLACE MACRO fdd.norm_unit(v) AS (
  LOWER(REGEXP_REPLACE(COALESCE(TRIM(CAST(v AS VARCHAR)), ''), '[^a-zA-Z0-9]', '', 'g'))
);

CREATE OR REPLACE MACRO fdd.quantity_for_sql_role(role) AS (
  CASE
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('ahu_sat', 'chw_return_t', 'chw_supply_sp', 'chw_supply_t',
      'cooling_coil_entering_temp', 'cooling_coil_leaving_temp', 'cooling_sp', 'cw_return_t',
      'cw_supply_t', 'heating_coil_entering_temp', 'heating_coil_leaving_temp', 'heating_sp',
      'hw_return_t', 'hw_supply_t', 'mat', 'oa_t', 'preheat_leave_t', 'rat', 'sat', 'sat_sp',
      'vav_discharge_t', 'vav_inlet_t', 'web_oa_dp', 'web_oa_t', 'web_wb_t', 'zone_air_temp_sp', 'zone_t')
      THEN 'absolute_temperature'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('ma_h', 'oa_h', 'ra_h', 'sa_h', 'web_oa_h', 'zone_rh')
      THEN 'relative_humidity'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chw_dp', 'chw_dp_sp', 'duct_static', 'duct_static_sp') THEN 'air_pressure'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chw_flow', 'min_flow_sp', 'vav_total_flow', 'zone_airflow_sp', 'zone_flow') THEN 'volume_flow'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chiller_power', 'electric_kw') THEN 'power'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('electric_kwh', 'kwh') THEN 'energy'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chiller_amps', 'chiller_current') THEN 'electric_current'
    WHEN TRIM(CAST(role AS VARCHAR)) = 'zone_co2' THEN 'concentration'
    WHEN TRIM(CAST(role AS VARCHAR)) IN ('chw_reset_request_sum', 'hw_reset_request_sum', 'static_reset_request') THEN 'count'
    ELSE NULL
  END
);

CREATE OR REPLACE MACRO fdd.unit_declares_quantity(unit, quantity) AS (
  CASE
    WHEN unit IS NULL OR TRIM(CAST(unit AS VARCHAR)) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN fdd.norm_unit(unit) IN ('c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN (
      fdd.norm_unit(unit) IN ('pct', 'percent', 'percent0100', 'rh', 'percentrelativehumidity')
      OR STRPOS(CAST(unit AS VARCHAR), '%') > 0
    )
    WHEN quantity = 'air_pressure' THEN fdd.norm_unit(unit) IN ('pa', 'pascal')
    WHEN quantity = 'volume_flow' THEN fdd.norm_unit(unit) = 'ls'
    WHEN quantity = 'power' THEN fdd.norm_unit(unit) = 'kw'
    WHEN quantity = 'energy' THEN fdd.norm_unit(unit) = 'kwh'
    WHEN quantity = 'electric_current' THEN fdd.norm_unit(unit) = 'a'
    WHEN quantity = 'concentration' THEN fdd.norm_unit(unit) = 'ppm'
    WHEN quantity = 'count' THEN fdd.norm_unit(unit) = 'count'
    ELSE false
  END
);

CREATE OR REPLACE MACRO fdd.is_expected_constant_sql_role(role) AS (
  CASE
    WHEN role IS NULL OR TRIM(CAST(role AS VARCHAR)) = '' THEN false
    WHEN fdd.norm_unit(role) LIKE '%sp' THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'setpoint') > 0 THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'status') > 0 THEN true
    WHEN fdd.norm_unit(role) LIKE '%cmd' THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'command') > 0 THEN true
    WHEN fdd.norm_unit(role) = 'occmode' THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'occupied') > 0 THEN true
    WHEN STRPOS(fdd.norm_unit(role), 'occupancy') > 0 THEN true
    WHEN fdd.norm_unit(role) = 'loopenabled' THEN true
    ELSE false
  END
);

CREATE OR REPLACE MACRO fdd.sweep_assessable_sql_role(role, unit) AS (
  CASE
    WHEN fdd.is_expected_constant_sql_role(role) THEN false
    ELSE fdd.unit_declares_quantity(unit, fdd.quantity_for_sql_role(role))
  END
);

CREATE OR REPLACE MACRO fdd.mask_sweep_val(role, unit, val) AS (
  CASE WHEN fdd.sweep_assessable_sql_role(role, unit) THEN CAST(val AS DOUBLE) ELSE NULL END
);

CREATE OR REPLACE MACRO to_char(ts, fmt) AS (
  CASE
    WHEN fmt = 'YYYY-MM' THEN strftime(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC', '%Y-%m')
    WHEN fmt = 'YYYY-MM-DD' THEN strftime(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC', '%Y-%m-%d')
    ELSE strftime(CAST(ts AS TIMESTAMPTZ) AT TIME ZONE 'UTC', fmt)
  END
);
