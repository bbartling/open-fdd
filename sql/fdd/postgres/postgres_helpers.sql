-- Install once on PostgreSQL in a schema controlled by the application owner.
CREATE SCHEMA IF NOT EXISTS fdd;
CREATE OR REPLACE FUNCTION fdd.try_double(value text)
RETURNS double precision
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
  RETURN trim(value)::double precision;
EXCEPTION
  WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN NULL;
END;
$$;

-- Sensor sweep assessability (twin of pandas sensor_sweep_catalog). Long-form inputs are SI only:
-- each sample is assessed only when its declared unit matches the role's SI quantity. Any other
-- unit, or none, masks that sample; nothing is converted or guessed here.
CREATE OR REPLACE FUNCTION fdd.norm_unit(value text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT lower(regexp_replace(coalesce(btrim(value), ''), '[^a-zA-Z0-9]', '', 'g'));
$$;

CREATE OR REPLACE FUNCTION fdd.quantity_for_sql_role(role text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN btrim(role) IN ('ahu_sat', 'chw_return_t', 'chw_supply_sp', 'chw_supply_t',
      'cooling_coil_entering_temp', 'cooling_coil_leaving_temp', 'cooling_sp', 'cw_return_t',
      'cw_supply_t', 'heating_coil_entering_temp', 'heating_coil_leaving_temp', 'heating_sp',
      'hw_return_t', 'hw_supply_t', 'mat', 'oa_t', 'preheat_leave_t', 'rat', 'sat', 'sat_sp',
      'vav_discharge_t', 'vav_inlet_t', 'web_oa_dp', 'web_oa_t', 'web_wb_t', 'zone_air_temp_sp', 'zone_t')
      THEN 'absolute_temperature'
    WHEN btrim(role) IN ('ma_h', 'oa_h', 'ra_h', 'sa_h', 'web_oa_h', 'zone_rh')
      THEN 'relative_humidity'
    WHEN btrim(role) IN ('chw_dp', 'chw_dp_sp', 'duct_static', 'duct_static_sp') THEN 'air_pressure'
    WHEN btrim(role) IN ('chw_flow', 'min_flow_sp', 'vav_total_flow', 'zone_airflow_sp', 'zone_flow') THEN 'volume_flow'
    WHEN btrim(role) IN ('chiller_power', 'electric_kw') THEN 'power'
    WHEN btrim(role) IN ('electric_kwh', 'kwh') THEN 'energy'
    WHEN btrim(role) IN ('chiller_amps', 'chiller_current') THEN 'electric_current'
    WHEN btrim(role) = 'zone_co2' THEN 'concentration'
    WHEN btrim(role) IN ('chw_reset_request_sum', 'hw_reset_request_sum', 'static_reset_request') THEN 'count'
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.unit_declares_quantity(unit text, quantity text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN unit IS NULL OR btrim(unit) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN
      fdd.norm_unit(unit) IN ('c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN
      fdd.norm_unit(unit) IN ('pct', 'percent', 'rh', 'percentrelativehumidity')
      OR position('%' IN unit) > 0
    WHEN quantity = 'air_pressure' THEN
      fdd.norm_unit(unit) IN ('pa', 'pascal')
    WHEN quantity = 'volume_flow' THEN
      fdd.norm_unit(unit) = 'ls'
    WHEN quantity = 'power' THEN
      fdd.norm_unit(unit) = 'kw'
    WHEN quantity = 'energy' THEN
      fdd.norm_unit(unit) = 'kwh'
    WHEN quantity = 'electric_current' THEN
      fdd.norm_unit(unit) = 'a'
    WHEN quantity = 'concentration' THEN
      fdd.norm_unit(unit) = 'ppm'
    WHEN quantity = 'count' THEN
      fdd.norm_unit(unit) = 'count'
    ELSE false
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.is_expected_constant_sql_role(role text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN btrim(role) = '' THEN false
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
$$;

CREATE OR REPLACE FUNCTION fdd.sweep_assessable_sql_role(role text, unit text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN fdd.is_expected_constant_sql_role(role) THEN false
    ELSE fdd.unit_declares_quantity(unit, fdd.quantity_for_sql_role(role))
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.mask_sweep_val(role text, unit text, val double precision)
RETURNS double precision
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN fdd.sweep_assessable_sql_role(role, unit) THEN val ELSE NULL END;
$$;
