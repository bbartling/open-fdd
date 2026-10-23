-- Portal inventory identity on point_map (forward-only, idempotent).
--
-- portal_point_id is the stable source point id from a Normal Framework
-- portal inventory. One point_map row per (site_id, portal_point_id): a
-- re-poll reuses that row's openfdd_key and never mints a second series.
-- referenced is false when the latest successful inventory no longer lists
-- the point. Its samples stay in the historian as orphaned data until an
-- operator purges them.
ALTER TABLE point_map ADD COLUMN IF NOT EXISTS portal_point_id text;
ALTER TABLE point_map ADD COLUMN IF NOT EXISTS referenced boolean NOT NULL DEFAULT true;
ALTER TABLE point_map ADD COLUMN IF NOT EXISTS provider_instance_id text;
CREATE UNIQUE INDEX IF NOT EXISTS point_map_site_portal_point_uidx
  ON point_map (site_id, portal_point_id)
  WHERE portal_point_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS point_map_site_unreferenced_idx
  ON point_map (site_id)
  WHERE referenced = false;
