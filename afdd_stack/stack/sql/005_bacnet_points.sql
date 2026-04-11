-- BACnet device columns for Grafana device/point dropdowns
ALTER TABLE points
  ADD COLUMN IF NOT EXISTS bacnet_device_id text,
  ADD COLUMN IF NOT EXISTS object_identifier text,
  ADD COLUMN IF NOT EXISTS object_name text;
CREATE INDEX IF NOT EXISTS idx_points_device ON points (bacnet_device_id);
CREATE INDEX IF NOT EXISTS idx_points_site_device ON points (site_id, bacnet_device_id);
