-- Open-FDD on NF's TimescaleDB northbound database. Idempotent: safe to re-run any time, and it UPGRADES an
-- older install in place (function bodies are replaced, the existing daily job is altered, not duplicated).
-- Run order (hooks/lib/timescale.js install() does it for you): core.sql, adapter_nf.sql, then this file:
--   psql "$PGURL" -v ON_ERROR_STOP=1 -1 -f core.sql -f adapter_nf.sql -f install.sql
--   (-1 = one transaction, ON_ERROR_STOP: a refused upgrade must stop before the old tables are dropped)
-- Run it as the INSTALLER role (see README: installer vs runtime role).
--
-- core.sql (generated copy of sql/fdd/schema/core.sql) owns the Open-FDD tables fdd.point, fdd.rule_result and
-- fdd.rule_config. This file owns schema openfdd and the policy around them:
--   config               key/value settings: max_bytes (retention cap, default 100 GB),
--                        retention_allowlist (JSON array of "schema.table" source hypertables that MAY be trimmed,
--                        default [] = none), max_chunks_per_call (default 100), retention_last (result of the last real
--                        retention run), schema_version
--   fdd.rule_result      made a hypertable on window_end (30 day chunks) here; the table itself is core.sql
--   retention_scope()    the hypertables retention may touch: everything in schemas openfdd and fdd + the allowlist
--   enforce_size_cap()   drops the oldest chunks IN SCOPE until the scope fits under the cap (budgeted, explicit status)
--   retention_preview()  dry run of enforce_size_cap(): lists what would be dropped, drops nothing
--   size_cap_job()       procedure for a TimescaleDB job (daily) when the role may add_job
--   history_buckets()    time_bucket aggregates over nf_samples for long-range charts / CSV
-- Schema version 4 (5.0.16) UPGRADES v3 in one transaction: openfdd.fdd_results is copied into fdd.rule_result
-- (row-count guarded: a mismatch raises and leaves both tables untouched), then openfdd.fdd_results and
-- openfdd.retention_log are dropped.
-- NF's own tables (its connector `data` table, other apps' tables) are NEVER touched unless listed in
-- retention_allowlist. Needs: the timescaledb extension (NF's connector already creates it), CREATE on the database.

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
-- Opt-in list of NF / source hypertables retention may drop chunks from. Empty by default.
INSERT INTO openfdd.config (key, value) VALUES ('retention_allowlist', '[]'::jsonb)
ON CONFLICT (key) DO NOTHING;
-- Finite budget: at most this many chunks are dropped per enforce_size_cap() call.
INSERT INTO openfdd.config (key, value) VALUES ('max_chunks_per_call', to_jsonb(100))
ON CONFLICT (key) DO NOTHING;

-- Retention cap in bytes (value may be stored as a JSON number or string).
CREATE OR REPLACE FUNCTION openfdd.max_bytes() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT COALESCE((SELECT (value #>> '{}')::bigint FROM openfdd.config WHERE key = 'max_bytes'),
                  107374182400::bigint)
$$;

CREATE OR REPLACE FUNCTION openfdd.max_chunks_per_call() RETURNS int
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(greatest(1, (SELECT (value #>> '{}')::int FROM openfdd.config WHERE key = 'max_chunks_per_call')), 100)
$$;

-- ------------------------------------------------------------------ results hypertable (table = core.sql)
SELECT create_hypertable('fdd.rule_result', 'window_end',
                         chunk_time_interval => interval '30 days', if_not_exists => true, migrate_data => true);

-- ------------------------------------------------------------------ v3 -> v4: legacy results into the core table
-- One-time, guarded. Mapping: run_ts -> created_at, equip -> equipment_id, site -> site_id (NULL -> ''), sensor_ref ->
-- subject_key, metric -> metrics; status from fault_hours (> 0 FAULT, = 0 PASS, NULL INCONCLUSIVE); rule_hash and
-- config_hash '' (v3 did not record them); a missing or non-increasing window becomes (window_end - 1 second, window_end)
-- with diagnostics.legacy.window_defaulted. Rows that would share a primary key keep the newest run_ts.
DO $do$
DECLARE
  v_expected bigint;
  v_copied   bigint;
BEGIN
  IF to_regclass('openfdd.fdd_results') IS NULL THEN RETURN; END IF;
  CREATE TEMP TABLE legacy_map ON COMMIT DROP AS
  SELECT DISTINCT ON (m.site_id, m.equipment_id, m.rule_id, m.subject_key, m.window_start, m.window_end) m.*
  FROM (
    SELECT coalesce(r.site, '') AS site_id, r.equip AS equipment_id, r.rule_id, coalesce(r.sensor_ref, '') AS subject_key,
           CASE WHEN r.window_start IS NOT NULL AND r.window_end IS NOT NULL AND r.window_start < r.window_end
                THEN r.window_start ELSE coalesce(r.window_end, r.run_ts) - interval '1 second' END AS window_start,
           coalesce(r.window_end, r.run_ts) AS window_end,
           CASE WHEN r.fault_hours IS NULL THEN 'INCONCLUSIVE' WHEN r.fault_hours > 0 THEN 'FAULT' ELSE 'PASS' END AS status,
           r.fault_hours, r.covered_hours, r.fault_pct, r.role, r.engine, coalesce(r.metric, '{}'::jsonb) AS metrics,
           jsonb_build_object('legacy', jsonb_build_object('source', 'openfdd.fdd_results',
             'window_defaulted', NOT (r.window_start IS NOT NULL AND r.window_end IS NOT NULL AND r.window_start < r.window_end))) AS diagnostics,
           r.run_ts AS created_at
    FROM openfdd.fdd_results r
  ) m
  ORDER BY m.site_id, m.equipment_id, m.rule_id, m.subject_key, m.window_start, m.window_end, m.created_at DESC;
  SELECT count(*) INTO v_expected FROM legacy_map;
  INSERT INTO fdd.rule_result (site_id, equipment_id, rule_id, subject_key, window_start, window_end, status,
                               fault_hours, covered_hours, fault_pct, role, engine, metrics, diagnostics, created_at)
  SELECT site_id, equipment_id, rule_id, subject_key, window_start, window_end, status,
         fault_hours, covered_hours, fault_pct, role, engine, metrics, diagnostics, created_at
  FROM legacy_map
  ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS v_copied = ROW_COUNT;
  IF v_copied <> v_expected THEN
    RAISE EXCEPTION 'openfdd v4 upgrade refused: copied % of % legacy result rows into fdd.rule_result; openfdd.fdd_results was NOT dropped',
      v_copied, v_expected USING ERRCODE = 'data_exception';
  END IF;
  INSERT INTO openfdd.config (key, value)
  VALUES ('legacy_results_copied', jsonb_build_object('rows', v_copied, 'at', to_jsonb(now())))
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
  DROP TABLE openfdd.fdd_results;
END
$do$;

-- ------------------------------------------------------------------ retention scope
-- The allowlist as text[] of "schema.table". Validated against the existing hypertables; ANY problem
-- (not a JSON array of strings, unknown / not a hypertable / internal schema) raises: retention fails closed.
CREATE OR REPLACE FUNCTION openfdd.retention_allowlist() RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v       jsonb;
  el      jsonb;
  e       text;
  good    text[] := '{}';
  unknown text[] := '{}';
BEGIN
  SELECT c.value INTO v FROM openfdd.config c WHERE c.key = 'retention_allowlist';
  IF v IS NULL OR v = 'null'::jsonb THEN RETURN good; END IF;
  IF jsonb_typeof(v) <> 'array' THEN
    RAISE EXCEPTION 'openfdd.config retention_allowlist must be a JSON array of "schema.table" names (got %)', jsonb_typeof(v)
      USING ERRCODE = 'invalid_parameter_value';
  END IF;
  FOR el IN SELECT x FROM jsonb_array_elements(v) AS x LOOP
    IF jsonb_typeof(el) <> 'string' THEN
      unknown := unknown || el::text;
      CONTINUE;
    END IF;
    e := el #>> '{}';
    IF starts_with(e, '_timescaledb') OR NOT EXISTS (
         SELECT 1 FROM timescaledb_information.hypertables h
         WHERE (h.hypertable_schema || '.' || h.hypertable_name) = e) THEN
      unknown := unknown || e;
    ELSE
      good := good || e;
    END IF;
  END LOOP;
  IF cardinality(unknown) > 0 THEN
    RAISE EXCEPTION 'openfdd.config retention_allowlist has entries that are not existing hypertables: %', unknown
      USING ERRCODE = 'invalid_parameter_value';
  END IF;
  RETURN good;
END
$$;

-- Hypertables automatic retention may touch: all of schemas openfdd and fdd (only fdd.rule_result is a hypertable
-- there) + the allowlist. Nothing else.
CREATE OR REPLACE FUNCTION openfdd.retention_scope()
RETURNS TABLE (schema_name text, table_name text, reason text)
LANGUAGE sql STABLE AS $$
  SELECT h.hypertable_schema::text, h.hypertable_name::text,
         CASE WHEN h.hypertable_schema IN ('openfdd', 'fdd') THEN 'openfdd' ELSE 'allowlist' END
  FROM timescaledb_information.hypertables h
  WHERE h.hypertable_schema IN ('openfdd', 'fdd')
     OR (h.hypertable_schema || '.' || h.hypertable_name) = ANY (openfdd.retention_allowlist())
  ORDER BY 1, 2
$$;

-- Total size of the hypertables in retention scope (NOT every hypertable in the database).
CREATE OR REPLACE FUNCTION openfdd.hypertables_bytes() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(sum(hypertable_size(format('%I.%I', s.schema_name, s.table_name))), 0)::bigint
  FROM openfdd.retention_scope() s
$$;

-- ------------------------------------------------------------------ size cap
-- Drops the oldest chunk IN SCOPE (by chunk end time) over and over until the scope's total size is
-- <= max_bytes. The newest chunk of every hypertable is never dropped. Finite: at most
-- config.max_chunks_per_call chunks per call, and it stops when nothing droppable is left or a drop does not
-- shrink the total. Always returns an explicit status:
--   under_cap / cap_reached        done, total <= cap
--   chunk_budget_exhausted         over cap but the per-call budget is spent (next call continues)
--   no_progress                    over cap and nothing more can be dropped (only newest chunks remain): cap unreachable
--   refused_allowlist              retention_allowlist invalid / names unknown tables: NOTHING was dropped
--   skipped_locked                 another run holds the lock
--   error                          a drop failed (for example the role does not own that hypertable); see "error"
-- dry_run = true lists what would be dropped (would_drop[]) and drops nothing.
CREATE OR REPLACE FUNCTION openfdd.retention_run(max_bytes bigint, dry_run boolean DEFAULT false)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_max_chunks int := openfdd.max_chunks_per_call();
  v_scope   jsonb;
  v_cands   jsonb;
  v_c       jsonb;
  v_before  bigint;
  v_total   bigint;
  v_prev    bigint;
  v_bytes   bigint;
  v_rel     text;
  v_n       int := 0;
  v_stall   int := 0;
  v_status  text;
  v_err     text;
  v_list    jsonb := '[]'::jsonb;
  v_res     jsonb;
  i         int;
BEGIN
  IF NOT dry_run AND NOT pg_try_advisory_xact_lock(hashtext('openfdd.enforce_size_cap')) THEN
    RETURN jsonb_build_object('status', 'skipped_locked', 'dry_run', false, 'chunks_dropped', 0,
                              'reached_cap', false, 'max_bytes', max_bytes);
  END IF;

  BEGIN
    SELECT COALESCE(jsonb_agg(s.schema_name || '.' || s.table_name ORDER BY s.schema_name, s.table_name), '[]'::jsonb)
      INTO v_scope FROM openfdd.retention_scope() s;
  EXCEPTION WHEN OTHERS THEN
    v_res := jsonb_build_object('status', 'refused_allowlist', 'dry_run', dry_run, 'error', SQLERRM,
      'max_bytes', max_bytes, 'chunks_dropped', 0, 'reached_cap', false, 'dropped', '[]'::jsonb, 'scope', '[]'::jsonb);
    IF NOT dry_run THEN
      INSERT INTO openfdd.config (key, value) VALUES ('retention_last', v_res)
      ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
    END IF;
    RETURN v_res;
  END;

  v_before := openfdd.hypertables_bytes();
  v_total := v_before;

  SELECT COALESCE(jsonb_agg(jsonb_build_object(
           'hs', c.hypertable_schema, 'ht', c.hypertable_name, 'cn', c.chunk_name,
           'rs', c.range_start, 're', c.range_end)
         ORDER BY c.range_end, c.hypertable_schema, c.hypertable_name, c.chunk_name), '[]'::jsonb)
    INTO v_cands
  FROM timescaledb_information.chunks c
  JOIN openfdd.retention_scope() s
    ON s.schema_name = c.hypertable_schema::text AND s.table_name = c.hypertable_name::text
  WHERE c.range_end < (SELECT max(c2.range_end) FROM timescaledb_information.chunks c2
                       WHERE c2.hypertable_schema = c.hypertable_schema
                         AND c2.hypertable_name = c.hypertable_name);

  FOR i IN 0 .. jsonb_array_length(v_cands) - 1 LOOP
    EXIT WHEN v_total <= max_bytes;
    IF v_n >= v_max_chunks THEN v_status := 'chunk_budget_exhausted'; EXIT; END IF;
    v_c := v_cands -> i;
    v_rel := format('%I.%I', v_c ->> 'hs', v_c ->> 'ht');
    SELECT s.total_bytes INTO v_bytes FROM chunks_detailed_size(v_rel::regclass) s WHERE s.chunk_name = v_c ->> 'cn';
    v_bytes := COALESCE(v_bytes, 0);
    IF dry_run THEN
      v_total := v_total - v_bytes;
    ELSE
      BEGIN
        -- exactly this chunk: older_than = its end, newer_than = its start
        PERFORM drop_chunks(v_rel::regclass, older_than => (v_c ->> 're')::timestamptz, newer_than => (v_c ->> 'rs')::timestamptz);
      EXCEPTION WHEN OTHERS THEN
        v_status := 'error';
        v_err := SQLERRM;
        EXIT;
      END;
      v_prev := v_total;
      v_total := openfdd.hypertables_bytes();
      IF v_total >= v_prev THEN v_stall := v_stall + 1; ELSE v_stall := 0; END IF;
    END IF;
    v_n := v_n + 1;
    v_list := v_list || jsonb_build_array(jsonb_build_object(
      'hypertable', v_rel, 'chunk', v_c ->> 'cn', 'range_start', v_c ->> 'rs', 'range_end', v_c ->> 're', 'bytes', v_bytes));
    IF v_stall >= 3 THEN v_status := 'no_progress'; EXIT; END IF;
  END LOOP;

  IF v_status IS NULL THEN
    IF v_total <= max_bytes THEN
      v_status := CASE WHEN v_n = 0 THEN 'under_cap' ELSE 'cap_reached' END;
    ELSE
      v_status := 'no_progress';   -- cap unreachable: only the protected newest chunks (or nothing) remain in scope
    END IF;
  END IF;

  v_res := jsonb_build_object(
    'status', v_status, 'dry_run', dry_run, 'max_bytes', max_bytes, 'max_chunks', v_max_chunks,
    'before_bytes', v_before, 'after_bytes', v_total,
    'reached_cap', v_total <= max_bytes,
    'chunks_dropped', CASE WHEN dry_run THEN 0 ELSE v_n END,
    'dropped', CASE WHEN dry_run THEN '[]'::jsonb ELSE v_list END,
    'scope', v_scope);
  IF dry_run THEN
    v_res := v_res || jsonb_build_object('chunks_would_drop', v_n, 'would_drop', v_list);
  END IF;
  IF v_err IS NOT NULL THEN v_res := v_res || jsonb_build_object('error', v_err); END IF;
  IF NOT dry_run THEN
    INSERT INTO openfdd.config (key, value) VALUES ('retention_last', v_res)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
  END IF;
  RETURN v_res;
END
$$;

-- Same name and arguments as the pre-scoped release, so the old job / callers pick up the scoped body.
CREATE OR REPLACE FUNCTION openfdd.enforce_size_cap(max_bytes bigint DEFAULT (100::bigint * 1024 * 1024 * 1024))
RETURNS jsonb
LANGUAGE sql AS $$
  SELECT openfdd.retention_run(max_bytes, false)
$$;

-- Dry run: what enforce_size_cap(max_bytes) would drop right now. Drops nothing, writes nothing.
CREATE OR REPLACE FUNCTION openfdd.retention_preview(max_bytes bigint DEFAULT openfdd.max_bytes())
RETURNS jsonb
LANGUAGE sql AS $$
  SELECT openfdd.retention_run(max_bytes, true)
$$;

-- TimescaleDB job entry point (reads the cap from openfdd.config; result goes to the server log + config retention_last).
CREATE OR REPLACE PROCEDURE openfdd.size_cap_job(job_id int, config jsonb)
LANGUAGE plpgsql AS $$
DECLARE r jsonb;
BEGIN
  r := openfdd.enforce_size_cap(openfdd.max_bytes());
  RAISE LOG 'openfdd.size_cap_job: %', r;
END
$$;

-- Daily job when the role may add_job; otherwise the hook calls enforce_size_cap once a day.
-- UPGRADE: an already-installed job (it calls openfdd.size_cap_job, whose body was just replaced by the scoped
-- version) is ALTERED in place and marked scoped; duplicates are removed. There is never a second job and never
-- an old global one left running. config.job_registered tells the hook which it is.
DO $do$
DECLARE
  v_keep int;
  v_cfg  jsonb := '{"scope": "openfdd+fdd+allowlist", "schema_version": 4}'::jsonb;
BEGIN
  SELECT min(job_id) INTO v_keep FROM timescaledb_information.jobs
  WHERE proc_schema = 'openfdd' AND proc_name = 'size_cap_job';
  IF v_keep IS NULL THEN
    PERFORM add_job('openfdd.size_cap_job', interval '1 day', config => v_cfg, initial_start => now() + interval '1 hour');
  ELSE
    PERFORM delete_job(j.job_id) FROM timescaledb_information.jobs j
    WHERE j.proc_schema = 'openfdd' AND j.proc_name = 'size_cap_job' AND j.job_id <> v_keep;
    PERFORM alter_job(v_keep, scheduled => true, config => v_cfg);
  END IF;
  INSERT INTO openfdd.config (key, value) VALUES ('job_registered', 'true'::jsonb)
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'add_job / alter_job not available (%), the fdd hook will enforce the cap daily', SQLERRM;
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

-- v4: the retention log is gone (the last real retention result lives in config retention_last). retention_run() above
-- no longer references it, so nothing depends on it.
DROP TABLE IF EXISTS openfdd.retention_log;

-- Last statement: mark the schema after the migration succeeds.
INSERT INTO openfdd.config (key, value) VALUES ('schema_version', to_jsonb(4))
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
