-- W2c (#1284): one-time in-place SI cutover ledger + tuning revision storage.
-- Forward-only. Rollback is restore-only (W9 pg_dump).

CREATE TABLE IF NOT EXISTS unit_migration (
  site_id text NOT NULL,
  openfdd_key text NOT NULL,
  from_unit text NOT NULL,
  to_unit text NOT NULL,
  row_count bigint NOT NULL CHECK (row_count >= 0),
  started_at timestamptz NOT NULL,
  finished_at timestamptz NOT NULL,
  checksum text NOT NULL,
  PRIMARY KEY (site_id, openfdd_key, checksum)
);

CREATE INDEX IF NOT EXISTS unit_migration_site_idx
  ON unit_migration (site_id, finished_at DESC);

ALTER TABLE point_map ADD COLUMN IF NOT EXISTS si_cutover_exclude boolean NOT NULL DEFAULT false;

-- Saved rule tuning revisions (starter from sql/fdd/tuning_storage.sql).
CREATE SCHEMA IF NOT EXISTS fdd;

CREATE TABLE IF NOT EXISTS fdd.rule_config_revision (
  tenant_id text NOT NULL,
  site_id text NOT NULL,
  rule_id text NOT NULL,
  scope_key text NOT NULL,
  revision bigint NOT NULL,
  parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters) = 'object'),
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  created_by text NOT NULL,
  PRIMARY KEY (tenant_id, site_id, rule_id, scope_key, revision)
);

CREATE TABLE IF NOT EXISTS fdd.active_rule_config (
  tenant_id text NOT NULL,
  site_id text NOT NULL,
  rule_id text NOT NULL,
  scope_key text NOT NULL,
  revision bigint NOT NULL,
  PRIMARY KEY (tenant_id, site_id, rule_id, scope_key),
  FOREIGN KEY (tenant_id, site_id, rule_id, scope_key, revision)
    REFERENCES fdd.rule_config_revision (tenant_id, site_id, rule_id, scope_key, revision)
);
