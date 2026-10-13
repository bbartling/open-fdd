-- Main postgres_helpers.sql defines fdd.try_double first.
CREATE OR REPLACE FUNCTION fdd.fdd_try_double(value text) RETURNS double precision
LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS 'SELECT fdd.try_double(value)';
CREATE OR REPLACE FUNCTION fdd.fdd_is_nan(value double precision) RETURNS integer
LANGUAGE SQL IMMUTABLE PARALLEL SAFE AS 'SELECT CASE WHEN value = ''NaN''::double precision THEN 1 ELSE 0 END';
CREATE OR REPLACE FUNCTION fdd.fdd_elapsed_seconds(start_time timestamptz,end_time timestamptz) RETURNS double precision
LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS 'SELECT EXTRACT(EPOCH FROM (end_time-start_time))::double precision';
CREATE OR REPLACE FUNCTION fdd.fdd_hour_bucket_utc(value timestamptz) RETURNS timestamp
LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE AS 'SELECT date_trunc(''hour'',value AT TIME ZONE ''UTC'')';
CREATE OR REPLACE FUNCTION fdd.fdd_month_key_utc(value timestamptz) RETURNS text
LANGUAGE SQL STABLE STRICT PARALLEL SAFE AS 'SELECT to_char(value AT TIME ZONE ''UTC'',''YYYY-MM'')';
