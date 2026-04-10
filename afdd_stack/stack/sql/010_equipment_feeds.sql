-- Brick-style equipment relationships: feeds (this equipment feeds that one), fed_by (this is fed by that).
-- Used for system tagging and emitted as brick:feeds / brick:isFedBy in TTL.
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS feeds_equipment_id uuid REFERENCES equipment(id) ON DELETE SET NULL;
ALTER TABLE equipment ADD COLUMN IF NOT EXISTS fed_by_equipment_id uuid REFERENCES equipment(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_equipment_feeds ON equipment(feeds_equipment_id);
CREATE INDEX IF NOT EXISTS idx_equipment_fed_by ON equipment(fed_by_equipment_id);
