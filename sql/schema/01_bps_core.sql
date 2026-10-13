-- BPS Timescale historian + FDD results (ADR 0009).
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS site (
  site_id       text PRIMARY KEY,
  dis           text,
  timezone      text NOT NULL DEFAULT 'UTC',
  enabled       boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS point_map (
  site_id       text NOT NULL REFERENCES site(site_id),
  openfdd_key   text NOT NULL,
  haystack_id   text NOT NULL,
  role          text,
  unit          text,
  equipment_id  text,
  PRIMARY KEY (site_id, openfdd_key)
);

-- Long/narrow samples. Opaque timeseries identity = (site_id, openfdd_key).
CREATE TABLE IF NOT EXISTS sample (
  ts            timestamptz NOT NULL,
  site_id       text NOT NULL,
  openfdd_key   text NOT NULL,
  haystack_id   text,
  val           double precision,
  unit          text,
  quality       text,
  PRIMARY KEY (site_id, openfdd_key, ts)
);

SELECT create_hypertable('sample', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS sample_site_key_ts_idx
  ON sample (site_id, openfdd_key, ts DESC);

-- Wide FDD input scratch is built per-run as TEMP tables (see sql_runner).
-- Persisted fault results:
CREATE TABLE IF NOT EXISTS fdd_run (
  run_id        bigserial PRIMARY KEY,
  site_id       text NOT NULL,
  equipment_id  text NOT NULL,
  rule_id       text NOT NULL,
  window_start  timestamptz NOT NULL,
  window_end    timestamptz NOT NULL,
  poll_seconds  integer NOT NULL DEFAULT 300,
  confirm_min   double precision NOT NULL DEFAULT 0,
  config_hash   text,
  status        text NOT NULL,
  fault_seconds integer,
  fault_hours   double precision,
  sample_count  integer,
  detail        jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fdd_run_site_rule_idx
  ON fdd_run (site_id, rule_id, window_end DESC);

CREATE TABLE IF NOT EXISTS batch_job (
  job_id        bigserial PRIMARY KEY,
  kind          text NOT NULL,
  site_id       text,
  range_name    text,
  status        text NOT NULL,
  detail        jsonb,
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz
);
