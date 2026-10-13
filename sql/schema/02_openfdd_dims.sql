-- Open-FDD dimensions beyond BPS core (equiperType / roles / registry).
-- BPS sample + fdd_run live in 01_bps_core.sql.

CREATE TABLE IF NOT EXISTS building (
  building_id   text PRIMARY KEY,
  site_id       text REFERENCES site(site_id),
  dis           text,
  timezone      text NOT NULL DEFAULT 'UTC',
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS equipment (
  building_id     text NOT NULL REFERENCES building(building_id),
  equipment_id    text NOT NULL,
  -- Stamped equipType / equipment_type only — never invent from id text.
  equip_type      text,
  parent_equipment_id text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (building_id, equipment_id)
);

CREATE INDEX IF NOT EXISTS equipment_building_type_idx
  ON equipment (building_id, equip_type);

-- Role map: openfdd_key ↔ SQL role column for wide TEMP history.
CREATE TABLE IF NOT EXISTS role_map (
  building_id   text NOT NULL,
  equipment_id  text NOT NULL,
  openfdd_key   text NOT NULL,
  role          text NOT NULL,
  unit          text,
  PRIMARY KEY (building_id, equipment_id, openfdd_key)
);

CREATE TABLE IF NOT EXISTS fdd_rule_registry (
  rule_id       text PRIMARY KEY,
  sql_file      text NOT NULL,
  title         text,
  equipment_kinds text[],
  required_roles text[],
  optional_roles text[],
  parity_status text,
  enabled       boolean NOT NULL DEFAULT true,
  detail        jsonb
);

-- Analytics result cache (replaces analytics_results/ Parquet).
CREATE TABLE IF NOT EXISTS analytics_result (
  building_id   text NOT NULL,
  query_id      text NOT NULL,
  query_version text NOT NULL,
  window_key    text NOT NULL,
  config_hash   text NOT NULL,
  stale         boolean NOT NULL DEFAULT false,
  payload       jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (building_id, query_id, query_version, window_key, config_hash)
);

CREATE TABLE IF NOT EXISTS seed_meta (
  key           text PRIMARY KEY,
  value         text NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
