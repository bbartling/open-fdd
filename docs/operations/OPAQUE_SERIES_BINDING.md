# Opaque series binding

Policy id: `retroactive-current-binding-v1`.

The historian key is `(site_id, openfdd_key)`. `openfdd_key`, `portal_point_id`, and `provider_instance_id` are opaque. They are not parsed as `equipment.role`.

`point_map` and `role_map` are the current authorized binding. Inspect, RCx, FDD, and exports join those maps to `sample`. A row is visible only when both maps agree on equipment and role and `point_map.referenced` is true.

## Retroactive current binding

A role edit or an equipment reparent updates the maps. Sample rows stay on the same key, with the same timestamps and values. Readers then apply the new equipment and role to every sample of that key, including samples stored before the edit.

That is retroactive classification of one stable series.

## Effective time

Effective-time classification is not implemented. The maps do not store `valid_from` or `valid_to`. Readers do not reconstruct the binding that was current when a sample was written. A correction applies to the whole series.

## Ambiguous roles and purge

Two referenced keys bound to the same equipment and role stay distinct. A wide input (Inspect pivot, FDD history, economizer, weather projection) uses that role only when exactly one key is bound. It does not average or max the candidates.

FDD history timestamps come from that equipment's unique bindings. A weather or chilled-water fallback adds timestamps only from the one stamped equipment chosen for that role. Samples belonging to any other equipment do not add rows.

`referenced = false` hides a series from readers and leaves its samples in place. A point purge deletes `sample`, `point_map`, and `role_map` rows for that one key.

## Migration and rollback

`sql/schema/07_opaque_series_binding.sql` creates `authorized_series`. It does not update, delete, or rewrite `sample`. Existing rows stay. Rolling the application back leaves the view in place and does not restore or remove samples. Dropping the view later removes only the view.
