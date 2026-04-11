-- Modbus TCP metering points (Open-FDD scraper + Brick TTL extension)
-- One JSON object per point: host, port, unit_id, timeout, function, address, count, decode?, scale?, offset?, label?
ALTER TABLE points ADD COLUMN IF NOT EXISTS modbus_config jsonb;
CREATE INDEX IF NOT EXISTS idx_points_modbus_site ON points (site_id) WHERE modbus_config IS NOT NULL;
