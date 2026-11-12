-- Open-FDD core schema, core_version 4. The one set of tables Open-FDD (NF Timescale) and every downstream app share.
-- Idempotent. Open-FDD owns every byte; applications vendor this file unchanged (compare bytes, never edit).
-- No hypertable calls and no app policy here: an application that wants hypertables adds them itself
-- (NF install.sql makes fdd.rule_result a hypertable on window_end, which is part of its primary key).
-- Samples are NOT part of the core: each application exposes its own as the view fdd.input_sample
-- (see "sources" in sql/fdd/input_contract.json).
CREATE SCHEMA IF NOT EXISTS fdd;

-- One row per bound point. NF: synced by the fdd hook from the Haystack model. Downstream apps: their point store.
CREATE TABLE IF NOT EXISTS fdd.point (
  site_id      text NOT NULL,
  point_key    text NOT NULL,                       -- NF point uuid | downstream openfdd_key; unique within site_id
  equipment_id text,
  role         text,                                -- history column / sensor role (input_contract.json)
  role_source  text,
  kind         text NOT NULL DEFAULT 'numeric' CHECK (kind IN ('numeric','bool','text')),
  unit         text,                                -- SI unit of fdd.input_sample.value (degC, Pa, L/s, kW, kWh, A, ppm, count, fraction, bool, %RH)
  source_unit  text,                                -- native unit when conversion happens at read time (NF), else NULL
  si_scale     double precision NOT NULL DEFAULT 1 CHECK (si_scale > 0 AND si_scale < 'Infinity'),
  si_offset    double precision NOT NULL DEFAULT 0 CHECK (abs(si_offset) < 'Infinity'),   -- value_si = value * si_scale + si_offset
  haystack_id  text,
  attrs        jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(attrs) = 'object'),        -- markers, dis, deviceRef, ...
  updated_at   timestamptz NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY (site_id, point_key)
);
CREATE INDEX IF NOT EXISTS point_equipment_role_idx ON fdd.point (site_id, equipment_id, role);

-- One row per (site, equipment, rule, subject, window, rule, config). Upsert key = PK (idempotent re-run).
CREATE TABLE IF NOT EXISTS fdd.rule_result (
  result_id            bigint GENERATED ALWAYS AS IDENTITY,     -- stable handle for APIs/UI; not unique across hypertable chunks, never a FK target
  site_id              text NOT NULL,
  equipment_id         text NOT NULL,
  rule_id              text NOT NULL,
  subject_key          text NOT NULL DEFAULT '',                -- sensor sweeps: point_key; '' = equipment level
  window_start         timestamptz NOT NULL,
  window_end           timestamptz NOT NULL CHECK (window_end > window_start),
  rule_hash            text NOT NULL DEFAULT '',
  config_hash          text NOT NULL DEFAULT '',
  config_revision      bigint,
  effective_parameters jsonb NOT NULL DEFAULT '{}',             -- includes confirm_min
  poll_seconds         double precision NOT NULL DEFAULT 300 CHECK (poll_seconds >= 1 AND poll_seconds < 'Infinity'),
  status               text NOT NULL CHECK (status IN ('PASS','FAULT','INCONCLUSIVE','SKIPPED','ERROR','STALE')),
  reason               text,
  fault_hours          double precision,                        -- NULL = not assessable
  covered_hours        double precision,
  fault_pct            double precision,
  role                 text,                                    -- sensor_role for sweeps
  engine               text,                                    -- 'timescale' | 'postgres-sql' | ...
  metrics              jsonb NOT NULL DEFAULT '{}',
  diagnostics          jsonb NOT NULL DEFAULT '{}',             -- sample_count, aggregates, provenance revisions, intervals:[{kind,start,end,...}]
  source_watermark     timestamptz,
  created_at           timestamptz NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY (site_id, equipment_id, rule_id, subject_key, window_start, window_end, rule_hash, config_hash)
);
CREATE INDEX IF NOT EXISTS rule_result_site_rule_idx ON fdd.rule_result (site_id, rule_id, window_end DESC);
CREATE INDEX IF NOT EXISTS rule_result_latest_idx    ON fdd.rule_result (site_id, equipment_id, rule_id, subject_key, created_at DESC);

-- Tuning: append-only revisions, at most one active per scope. site_id '' = global.
CREATE TABLE IF NOT EXISTS fdd.rule_config (
  site_id    text NOT NULL,
  rule_id    text NOT NULL,
  scope_key  text NOT NULL,                                     -- 'site' or application-encoded exact equipment scope
  revision   bigint NOT NULL,
  parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters) = 'object'),
  active     boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  created_by text NOT NULL,
  PRIMARY KEY (site_id, rule_id, scope_key, revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS rule_config_one_active ON fdd.rule_config (site_id, rule_id, scope_key) WHERE active;
-- Activation is one transaction: UPDATE ... SET active = false WHERE (site, rule, scope) AND active; then set the new revision active.
-- Add application authorization/RLS policies appropriate to your identity system.
