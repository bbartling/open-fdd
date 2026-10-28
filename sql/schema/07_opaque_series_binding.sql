-- Opaque series binding. Forward-only.
--
-- Policy retroactive-current-binding-v1:
-- A sample row is physical history. Its identity is (site_id, openfdd_key).
-- openfdd_key, portal_point_id, and provider_instance_id are opaque.
-- They are not equipment ids and they are not roles.
-- point_map and role_map hold the current authorized binding.
-- Readers join those maps. They do not split or rebuild openfdd_key.
-- A role edit or an equipment reparent updates the maps only.
-- Every sample of that key, including samples stored before the edit,
-- is then read under the new equipment and role. That is retroactive
-- classification of a stable series.
-- Effective-time classification is not implemented. The maps have no
-- valid_from or valid_to, and readers do not reconstruct an earlier binding.
-- referenced = false omits the series from readers. The sample rows stay
-- until an explicit purge of that one key.
-- Two referenced keys for one equipment and role stay distinct. A wide
-- input uses a role only when exactly one key is bound to it.
--
-- This statement creates a view. It does not rewrite sample rows.
-- Rollback of the application can ignore the view. Dropping the view
-- later does not remove samples, point_map rows, or role_map rows.

CREATE OR REPLACE VIEW authorized_series AS
SELECT
  pm.site_id,
  pm.openfdd_key,
  rm.equipment_id,
  rm.role,
  pm.unit,
  pm.quantity,
  pm.cadence_secs,
  pm.history_mode,
  pm.referenced,
  pm.portal_point_id,
  pm.provider_instance_id,
  pm.haystack_id
FROM point_map pm
JOIN role_map rm
  ON rm.building_id = pm.site_id
 AND rm.openfdd_key = pm.openfdd_key
 AND rm.equipment_id = pm.equipment_id
 AND rm.role = pm.role
WHERE pm.referenced;
