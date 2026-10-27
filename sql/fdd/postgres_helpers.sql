-- Install once on PostgreSQL in a schema controlled by the application owner.
-- Canonical copy: sql/fdd/postgres/postgres_helpers.sql (keep both in sync).
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

-- Sensor sweep assessability (twin of fdd_core::sensor_sweep / pandas sensor_sweep_catalog).
CREATE OR REPLACE FUNCTION fdd.norm_unit(value text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT lower(regexp_replace(coalesce(btrim(value), ''), '[^a-zA-Z0-9]', '', 'g'));
$$;

CREATE OR REPLACE FUNCTION fdd.quantity_for_sql_role(role text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE btrim(role)
    WHEN 'oa_t' THEN 'absolute_temperature'
    WHEN 'rat' THEN 'absolute_temperature'
    WHEN 'zone_t' THEN 'absolute_temperature'
    WHEN 'mat' THEN 'absolute_temperature'
    WHEN 'sat' THEN 'absolute_temperature'
    WHEN 'chw_supply_t' THEN 'absolute_temperature'
    WHEN 'chw_return_t' THEN 'absolute_temperature'
    WHEN 'hw_supply_t' THEN 'absolute_temperature'
    WHEN 'hw_return_t' THEN 'absolute_temperature'
    WHEN 'oa_h' THEN 'relative_humidity'
    WHEN 'ra_h' THEN 'relative_humidity'
    WHEN 'zone_rh' THEN 'relative_humidity'
    WHEN 'zone_h' THEN 'relative_humidity'
    WHEN 'ma_h' THEN 'relative_humidity'
    WHEN 'sa_h' THEN 'relative_humidity'
    WHEN 'duct_static' THEN 'air_pressure'
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.unit_declares_quantity(unit text, quantity text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN unit IS NULL OR btrim(unit) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN
      fdd.norm_unit(unit) IN ('f', 'degf', 'fahrenheit', 'c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN
      fdd.norm_unit(unit) IN ('pct', 'percent', 'rh', 'percentrelativehumidity')
      OR position('%' IN unit) > 0
    WHEN quantity = 'air_pressure' THEN
      fdd.norm_unit(unit) IN ('inwc', 'inh2o', 'inw.c.', 'pa', 'pascal')
      OR position('w.c' IN lower(unit)) > 0
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
