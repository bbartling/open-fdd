CREATE TABLE IF NOT EXISTS fault_definitions (
  fault_id      text PRIMARY KEY,          -- matches fault_results.fault_id (your "flag")
  name          text NOT NULL,              -- pretty label
  description   text NULL,
  severity      text NOT NULL DEFAULT 'warning',  -- info|warning|critical
  category      text NOT NULL DEFAULT 'general',  -- sensor_validation|ahu|vav|plant|energy|iaq|...
  equipment_types text[] NULL,              -- e.g. {AHU,VAV_AHU}
  inputs        jsonb NULL,                 -- cookbook inputs (brick classes)
  params        jsonb NULL,                 -- cookbook params
  expression    text NULL,                  -- cookbook expression (optional, but nice)
  source        text NULL,                  -- where it came from (file/rule name)
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fault_definitions_category_idx ON fault_definitions(category);
CREATE INDEX IF NOT EXISTS fault_definitions_equipment_types_idx ON fault_definitions USING gin(equipment_types);