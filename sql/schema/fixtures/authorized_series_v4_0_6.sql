-- Pre-W1a authorized_series definition (4.0.6 column order). Test fixture only.
-- Use after DROP VIEW; production DBs still have this shape before W1a forward DDL.

CREATE VIEW authorized_series AS
SELECT
  pm.site_id,
  pm.openfdd_key,
  rm.equipment_id,
  rm.role,
  rm.unit,
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
