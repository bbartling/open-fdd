-- Pack runtime catalog. Forward-only.
-- Does not drop, truncate, delete, or rewrite historian rows
-- (sample, equipment, point_map, role_map, fdd_run, analytics_result).
-- fdd.try_double is installed from sql/fdd/postgres/postgres_helpers.sql
-- immediately before this file. This statement only pins its search_path.

ALTER FUNCTION fdd.try_double(text) SET search_path = pg_catalog;

CREATE TABLE IF NOT EXISTS fdd.pack_runtime (
  contract_id text PRIMARY KEY,
  contract_version text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fdd.pack_runtime (contract_id, contract_version)
VALUES ('openfdd-postgres-pack', '1')
ON CONFLICT (contract_id) DO UPDATE
SET contract_version = EXCLUDED.contract_version,
    updated_at = now()
WHERE fdd.pack_runtime.contract_version IS DISTINCT FROM EXCLUDED.contract_version;

CREATE TABLE IF NOT EXISTS fdd.pack_helper (
  name text PRIMARY KEY,
  signature text NOT NULL
);

INSERT INTO fdd.pack_helper (name, signature)
VALUES ('fdd.try_double', 'fdd.try_double(text) returns double precision')
ON CONFLICT (name) DO UPDATE
SET signature = EXCLUDED.signature
WHERE fdd.pack_helper.signature IS DISTINCT FROM EXCLUDED.signature;

CREATE TABLE IF NOT EXISTS fdd.pack_input (
  relation_name text PRIMARY KEY,
  disposition text NOT NULL,
  scope text NOT NULL
);

INSERT INTO fdd.pack_input (relation_name, disposition, scope)
VALUES
  ('weather', 'scoped_projection', 'building_id and half-open sample window'),
  ('utility_interval', 'scoped_projection', 'building_id and half-open sample window; equip_type utility'),
  ('utility_monthly', 'scoped_projection', 'building_id and half-open sample window; equip_type utility')
ON CONFLICT (relation_name) DO UPDATE
SET disposition = EXCLUDED.disposition,
    scope = EXCLUDED.scope
WHERE fdd.pack_input.disposition IS DISTINCT FROM EXCLUDED.disposition
   OR fdd.pack_input.scope IS DISTINCT FROM EXCLUDED.scope;
