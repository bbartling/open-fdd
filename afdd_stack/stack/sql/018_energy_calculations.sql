-- FDD energy / savings calculation specs (knowledge graph + future analytics integration)
CREATE TABLE IF NOT EXISTS energy_calculations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    equipment_id uuid REFERENCES equipment(id) ON DELETE SET NULL,
    external_id text NOT NULL,
    name text NOT NULL,
    description text,
    calc_type text NOT NULL,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    point_bindings jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT energy_calculations_site_external_unique UNIQUE (site_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_energy_calculations_site ON energy_calculations(site_id);
CREATE INDEX IF NOT EXISTS idx_energy_calculations_equipment
    ON energy_calculations(equipment_id) WHERE equipment_id IS NOT NULL;
