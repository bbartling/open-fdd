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
