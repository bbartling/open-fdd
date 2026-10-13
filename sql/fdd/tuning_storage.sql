-- Starter schema for integration, not an automatically executed migration.
-- Application validates catalog ranges, rule existence, role availability and authorization.
CREATE SCHEMA IF NOT EXISTS fdd;
CREATE TABLE IF NOT EXISTS fdd.rule_config_revision (
  tenant_id text NOT NULL,
  site_id text NOT NULL,
  rule_id text NOT NULL,
  scope_key text NOT NULL, -- 'site' or application-encoded exact equipment scope
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
CREATE TABLE IF NOT EXISTS fdd.rule_result (
  tenant_id text NOT NULL,
  site_id text NOT NULL,
  equipment_id text NOT NULL,
  rule_id text NOT NULL,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL CHECK (window_end > window_start),
  rule_hash text NOT NULL,
  config_hash text NOT NULL,
  config_revision bigint,
  effective_parameters jsonb NOT NULL,
  poll_seconds double precision NOT NULL CHECK (poll_seconds >= 1 AND poll_seconds < 'Infinity'::double precision),
  status text NOT NULL CHECK (status IN ('ok','skipped','error')),
  reason text,
  metrics jsonb NOT NULL,
  diagnostics jsonb NOT NULL DEFAULT '{}',
  source_watermark timestamptz,
  created_at timestamptz NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY (tenant_id, site_id, equipment_id, rule_id, window_start, window_end, rule_hash, config_hash)
);
-- Add application authorization/RLS policies appropriate to your identity system.
-- Detail/series storage is application-specific and must retain the same config/rule hashes.
