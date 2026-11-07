-- The PRE-scoped retention functions (global across every user hypertable), used by the upgrade-path test to
-- recreate an already-installed old box. Test-only; never apply to a real database.
DO $guard$
BEGIN
  IF coalesce(shobj_description((SELECT oid FROM pg_database WHERE datname = current_database()), 'pg_database'), '')
       NOT LIKE 'openfdd-ts-test-disposable:%' THEN
    RAISE EXCEPTION 'legacy_global_retention.sql refused: not a disposable test database';
  END IF;
END
$guard$;

CREATE OR REPLACE FUNCTION openfdd.hypertables_bytes() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(sum(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name))), 0)::bigint
  FROM timescaledb_information.hypertables
  WHERE hypertable_schema NOT LIKE '\_timescaledb%'
$$;

CREATE OR REPLACE FUNCTION openfdd.enforce_size_cap(max_bytes bigint DEFAULT (100::bigint * 1024 * 1024 * 1024))
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_total   bigint := openfdd.hypertables_bytes();
  v_n       int := 0;
  rec       record;
BEGIN
  WHILE v_total > max_bytes LOOP
    SELECT c.hypertable_schema, c.hypertable_name, c.range_start, c.range_end INTO rec
    FROM timescaledb_information.chunks c
    WHERE c.hypertable_schema NOT LIKE '\_timescaledb%'
      AND c.range_end < (SELECT max(c2.range_end) FROM timescaledb_information.chunks c2
                         WHERE c2.hypertable_schema = c.hypertable_schema AND c2.hypertable_name = c.hypertable_name)
    ORDER BY c.range_end, c.hypertable_name LIMIT 1;
    EXIT WHEN NOT FOUND;
    PERFORM drop_chunks(format('%I.%I', rec.hypertable_schema, rec.hypertable_name), older_than => rec.range_end, newer_than => rec.range_start);
    v_n := v_n + 1;
    v_total := openfdd.hypertables_bytes();
  END LOOP;
  RETURN jsonb_build_object('chunks_dropped', v_n, 'reached_cap', v_total <= max_bytes);
END
$$;
