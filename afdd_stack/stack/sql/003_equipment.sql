-- Equipment and org hierarchy
CREATE TABLE IF NOT EXISTS equipment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name text NOT NULL,
    description text,
    equipment_type text,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_equipment_site ON equipment(site_id);

ALTER TABLE points ADD COLUMN IF NOT EXISTS equipment_id uuid REFERENCES equipment(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_points_equipment ON points(equipment_id);
