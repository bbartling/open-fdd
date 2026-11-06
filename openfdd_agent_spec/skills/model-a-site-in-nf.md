---
name: model-a-site-in-nf
description: Tag a site in Normal Framework so Open-FDD binds its rules and charts (use the NF MCP).
---
# Model a site in NF

The app has no site configuration; the NF Haystack model is the configuration. Never fork or edit the app per site.

1. Connect the NF MCP (`connect`); check `session` status and notes first.
2. Site record: latitude, longitude, timezone, optional `area` (ft2 unless `areaUnit` is m2). The weather hook and EUI use them.
3. Equipment: one equip instance per physical unit (`manage_equipment`) with kind markers (`ahu`, `vav`, `chiller`,
   `boiler`, `meter`, ...). Kinds come from `equipment_kinds` in `nf-app/static/fdd-catalog.json`.
4. Points (`tag_points`): `siteRef`, `equipRef`, `deviceRef`, NF `class` in dash-case (for example
   `discharge-air-temp-sensor`), `markers`, `kind`, `unit` (so ingest can convert to SI). Prefer a class over bare markers.
   Trend (history) every point to chart or run rules on. Tag spare I/O `spare`.
5. Verify in the app: FDD tab shows "missing inputs" per equip (roles not bound); RCx lists views that cannot draw;
   Model and RDF has no dangling references.

How NF stores the tags and how to query them from a terminal: `docs/operations/nf/haystack-tagging.md`
(`scripts/nf/tools/nf_portal_sensors.py --tags ...` prints the model tree and live values).

Never rename points to make them match; fix tags. Binding never reads names (`DATA_CONTRACT.md`).
Tests (when binding code changes): `node --test nf-app/tests/binding-issues.test.mjs nf-app/tests/rdf.test.mjs`.
