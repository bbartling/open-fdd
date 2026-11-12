-- The v3 results layout (openfdd.fdd_results hypertable + openfdd.retention_log), used by the v3 -> v4 upgrade tests to
-- recreate an already-installed 5.0.15 box. Test-only; never apply to a real database.
DO $guard$
BEGIN
  IF coalesce(shobj_description((SELECT oid FROM pg_database WHERE datname = current_database()), 'pg_database'), '')
       NOT LIKE 'openfdd-ts-test-disposable:%' THEN
    RAISE EXCEPTION 'legacy_v3_results.sql refused: not a disposable test database';
  END IF;
END
$guard$;

CREATE TABLE openfdd.fdd_results (
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
  sensor_ref      text             NOT NULL DEFAULT '',
  role            text,
  PRIMARY KEY (run_ts, equip, rule_id, sensor_ref)
);
SELECT create_hypertable('openfdd.fdd_results', 'run_ts', chunk_time_interval => interval '30 days', if_not_exists => true);
CREATE TABLE openfdd.retention_log (
  id      bigserial PRIMARY KEY,
  run_at  timestamptz NOT NULL DEFAULT now(),
  status  text        NOT NULL,
  dry_run boolean     NOT NULL DEFAULT false,
  result  jsonb       NOT NULL
);
