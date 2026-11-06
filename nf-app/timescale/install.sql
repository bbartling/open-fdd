-- Open-FDD on NF's TimescaleDB northbound database. Idempotent: safe to re-run any time.
-- Run adapter_nf.sql FIRST (hooks/lib/timescale.js install() does that for you):
--   psql "$PGURL" -f adapter_nf.sql -f install.sql
--
-- Creates (schema openfdd):
--   config               key/value settings (max_bytes = retention cap, default 100 GB)
--   fdd_results          hypertable of rule results written by the fdd hook
--   enforce_size_cap()   drops the oldest chunks until all hypertables fit under the cap
--   size_cap_job()       procedure for a TimescaleDB job (daily) when the role may add_job
--   history_buckets()    time_bucket aggregates over nf_samples for long-range charts / CSV
-- Needs: the timescaledb extension (NF's connector already creates it), CREATE on the database.

DO $do$
BEGIN
  CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'timescaledb extension not created (insufficient privilege); assuming it already exists';
END
$do$;

CREATE SCHEMA IF NOT EXISTS openfdd;

-- ------------------------------------------------------------------ config
CREATE TABLE IF NOT EXISTS openfdd.config (
  key   text PRIMARY KEY,
  value jsonb NOT NULL
);
INSERT INTO openfdd.config (key, value) VALUES ('max_bytes', to_jsonb(107374182400::bigint))
ON CONFLICT (key) DO NOTHING;

-- Retention cap in bytes (value may be stored as a JSON number or string).
CREATE OR REPLACE FUNCTION openfdd.max_bytes() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT COALESCE((SELECT (value #>> '{}')::bigint FROM openfdd.config WHERE key = 'max_bytes'),
                  107374182400::bigint)
$$;

-- ------------------------------------------------------------------ results hypertable
CREATE TABLE IF NOT EXISTS openfdd.fdd_results (
  run_ts          timestamptz      NOT NULL,
  equip           text             NOT NULL,
  site            text,
  rule_id         text             NOT NULL,
  fault_pct       double precision,
  fault_hours     double precision,
  covered_hours   double precision,
  metric          jsonb,
  engine          text,
  window_start    timestamptz,
  window_end      timestamptz,
  PRIMARY KEY (run_ts, equip, rule_id)
);
SELECT create_hypertable('openfdd.fdd_results', 'run_ts',
                         chunk_time_interval => interval '30 days', if_not_exists => true);
CREATE INDEX IF NOT EXISTS fdd_results_equip_rule_ts ON openfdd.fdd_results (equip, rule_id, run_ts DESC);

-- ------------------------------------------------------------------ size cap
-- Total size of every user hypertable (NF's data hypertable(s) + openfdd.fdd_results).
CREATE OR REPLACE FUNCTION openfdd.hypertables_bytes() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(sum(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name))), 0)::bigint
  FROM timescaledb_information.hypertables
  WHERE hypertable_schema NOT LIKE '\_timescaledb%'
$$;

-- Drops the oldest chunk (across all hypertables, by chunk end time) over and over until the total
-- hypertable size is <= max_bytes. The newest chunk of every hypertable is never dropped, so the
-- cap can be missed (reached_cap = false) when only newest chunks remain. Granularity = one chunk.
CREATE OR REPLACE FUNCTION openfdd.enforce_size_cap(max_bytes bigint DEFAULT (100::bigint * 1024 * 1024 * 1024))
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_before  bigint;
  v_total   bigint;
  v_dropped jsonb := '[]'::jsonb;
  v_n       int := 0;
  v_bytes   bigint;
  v_rel     text;
  rec       record;
BEGIN
  IF NOT pg_try_advisory_xact_lock(hashtext('openfdd.enforce_size_cap')) THEN
    RETURN jsonb_build_object('skipped', 'another enforce_size_cap is running');
  END IF;
  v_before := openfdd.hypertables_bytes();
  v_total := v_before;
  WHILE v_total > max_bytes LOOP
    SELECT c.hypertable_schema, c.hypertable_name, c.chunk_schema, c.chunk_name, c.range_start, c.range_end
      INTO rec
    FROM timescaledb_information.chunks c
    WHERE c.hypertable_schema NOT LIKE '\_timescaledb%'
      AND c.range_end < (SELECT max(c2.range_end) FROM timescaledb_information.chunks c2
                         WHERE c2.hypertable_schema = c.hypertable_schema
                           AND c2.hypertable_name = c.hypertable_name)
    ORDER BY c.range_end, c.hypertable_name
    LIMIT 1;
    EXIT WHEN NOT FOUND;

    v_rel := format('%I.%I', rec.hypertable_schema, rec.hypertable_name);
    SELECT COALESCE(s.total_bytes, 0) INTO v_bytes
    FROM chunks_detailed_size(v_rel) s WHERE s.chunk_name = rec.chunk_name;
    -- exactly this chunk: older_than = its end, newer_than = its start
    PERFORM drop_chunks(v_rel, older_than => rec.range_end, newer_than => rec.range_start);
    v_n := v_n + 1;
    v_dropped := v_dropped || jsonb_build_array(jsonb_build_object(
      'hypertable', v_rel, 'chunk', rec.chunk_name,
      'range_start', rec.range_start, 'range_end', rec.range_end, 'bytes', COALESCE(v_bytes, 0)));
    v_total := openfdd.hypertables_bytes();
  END LOOP;
  RETURN jsonb_build_object(
    'max_bytes', max_bytes, 'before_bytes', v_before, 'after_bytes', v_total,
    'chunks_dropped', v_n, 'reached_cap', v_total <= max_bytes, 'dropped', v_dropped);
END
$$;

-- TimescaleDB job entry point (reads the cap from openfdd.config; result goes to the server log).
CREATE OR REPLACE PROCEDURE openfdd.size_cap_job(job_id int, config jsonb)
LANGUAGE plpgsql AS $$
DECLARE r jsonb;
BEGIN
  r := openfdd.enforce_size_cap(openfdd.max_bytes());
  RAISE LOG 'openfdd.size_cap_job: %', r;
END
$$;

-- Daily job when the role may add_job; otherwise the hook calls enforce_size_cap once a day.
-- config.job_registered tells the hook which it is.
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.jobs
                 WHERE proc_schema = 'openfdd' AND proc_name = 'size_cap_job') THEN
    PERFORM add_job('openfdd.size_cap_job', interval '1 day', initial_start => now() + interval '1 hour');
  END IF;
  INSERT INTO openfdd.config (key, value) VALUES ('job_registered', 'true'::jsonb)
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'add_job not available (%), the fdd hook will enforce the cap daily', SQLERRM;
  INSERT INTO openfdd.config (key, value) VALUES ('job_registered', 'false'::jsonb)
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
END
$do$;

-- ------------------------------------------------------------------ long-range history
-- uuids = NF point uuids (text). Buckets are aligned to the Unix epoch (UTC).
CREATE OR REPLACE FUNCTION openfdd.history_buckets(
  uuids text[], from_ts timestamptz, to_ts timestamptz, bucket_width interval)
RETURNS TABLE (point_uuid text, bucket timestamptz, avg double precision, min double precision,
               max double precision, n bigint)
LANGUAGE sql STABLE AS $$
  SELECT s.point_uuid AS point_uuid,
         time_bucket(bucket_width, s.ts, timestamptz '1970-01-01 00:00:00+00') AS bucket,
         avg(s.value) AS avg, min(s.value) AS min, max(s.value) AS max, count(s.value) AS n
  FROM openfdd.nf_samples s
  WHERE s.point_uuid = ANY (uuids) AND s.ts >= from_ts AND s.ts < to_ts
  GROUP BY 1, 2
  ORDER BY 1, 2
$$;
