-- Enforce at most one equipment per (site_id, name) to match RDF semantics and prevent duplicate rows in UI.
-- Dedupe existing data: keep one equipment per (site_id, name), reassign points to it, drop others, then add constraint.
--
-- Existing DBs (not fresh install): run this file manually, e.g. from stack/:
--   docker compose exec db psql -U postgres -d openfdd -f - < sql/016_equipment_unique_site_name.sql
-- Or: psql $OFDD_DB_DSN -f stack/sql/016_equipment_unique_site_name.sql

-- 1. For each (site_id, name) with duplicates, keep the equipment with the smallest id and reassign points.
DO $$
DECLARE
  dup RECORD;
  keep_id uuid;
BEGIN
  FOR dup IN
    SELECT site_id, name, array_agg(id ORDER BY id) AS ids
    FROM equipment
    GROUP BY site_id, name
    HAVING count(*) > 1
  LOOP
    keep_id := dup.ids[1];
    UPDATE points SET equipment_id = keep_id
    WHERE equipment_id = ANY(dup.ids) AND equipment_id != keep_id;
    DELETE FROM equipment WHERE site_id = dup.site_id AND name = dup.name AND id != keep_id;
  END LOOP;
END $$;

-- 2. Add unique constraint (no-op if already present from a previous run).
ALTER TABLE equipment
  DROP CONSTRAINT IF EXISTS equipment_site_id_name_key;

ALTER TABLE equipment
  ADD CONSTRAINT equipment_site_id_name_key UNIQUE (site_id, name);
