---
name: openfdd-package-mapping
description: >-
  Author an openfdd_package_v1 zip for any BAS job: equipType, Haystack points
  to SQL roles, weather sidecar, motor vs compressor vs valve. Triggers on
  package zip, column_map, mapping, empty Overview / RCx / Inspect charts,
  missing roles, haystack sidecar.
---

# Open-FDD package mapping (any BAS job)

Read [`docs/agent/PACKAGE_AUTHORING.md`](../../../docs/agent/PACKAGE_AUTHORING.md)
and [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../../../docs/migration/vibe19/ROLE_MAPPING_PARITY.md).

Modeling (agent context, docs-only expansions):

- [`docs/modeling/package-schema.md`](../../../docs/modeling/package-schema.md) — compact ingest map vs SCAFFOLD evidence
- [`docs/modeling/heat-pump-buildings.md`](../../../docs/modeling/heat-pump-buildings.md) — WSHP topology + role tiers
- [`docs/modeling/rule-readiness.md`](../../../docs/modeling/rule-readiness.md) — runnable / not_runnable / unknown

## When to use

- Building a zip / sidecar `column_map` / Haystack `points`
- Overview tables, RCx plots, Inspect overlay, or health matrices are empty
- Agent is guessing equipment type from folder names
- Heat-pump / geo-loop building packages (do not copy AHU/VAV BUILDING_100 topology)

## Rules

1. Empty analytics = **missing roles in the zip**, not a broken FDD engine. Map in preprocess. A parseable ZIP is **not** commissioning-grade FDD.
2. Stamp `equipType` (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`). `rtu`→AHU; `heatPump`→HP; UV/FCU air-side→ahu; chillers→chwPlant. Do **not** stamp a source-water / geo loop as `chwPlant` just to light CHW analytics.
3. **Shipped ingest** = compact sibling JSON: `equipType` + `points: { haystack-name: csv-header }`. Rich `column`/`role`/`unit`/`confidence` / PROVISIONAL maps in the MCP package-mapping role pack are **SCAFFOLD** — not the live importer.
4. Haystack names in `points` translate via `haystack_point_to_role`. Do not invent a second product vocabulary.
5. Motor ≠ compressor ≠ valve. Status/cmd before amps. Never CHW pump or `clg_valve_pct` as compressor proof. Never motor hours from leave temp. Never infer compressor from fan status; never invent mode/setpoint columns.
6. Weather lives at `{building}/weather/` with `web-outside-air-temp` → `web_oa_t`. Distinguish BAS `oa_t` from web `web_oa_t`. Lat/lon in preprocess. `prefer_web_oat`.
7. `timestamp_utc` is RFC3339 (`Z` or `+00:00`). String `"equip": "AHU_1"` is metadata.
8. Import with existing `POST /api/csv/import/package` + MCP `openfdd_csv_import_*` / `openfdd_csv_package_append`. For **streaming sim** on Liberty B50: host script `scripts/csv_flood_afdd_routine_sim.py` (append + AFDD routine patches). Do **not** implement SCAFFOLD `mapping_suggest` / `package_preflight` this cycle.
9. No vendor/city hardcoding in product. Gold ids: `AHU_1` / `VAV_1` / `CHW_1` / `weather/`.
10. **HP-1 caveat:** registry may list `fan_status` optional while SQL still gates on `fan_cmd` — fan-status-only packages are typically **not runnable**. Do not map binary fan status into fake percent `fan_cmd`. See rule-readiness doc.

## Anti-patterns

- Patching SQL because a plot is empty
- Porting vibe19 Streamlit Data Model into the SPA
- Documenting SCAFFOLD mapping tools as if they drive Central import
- Modeling WSHPs as VAVs or flattening floor “areas” as proven thermal zones without BAS evidence
- Duplicating this skill into `~/.cursor/skills/`

## Stamped equipment types

Prefer stamping `equipType` (or `equipment_type`) in each equipment map. Open-FDD persists and prefers the stamp over folder-id inference. If an Overview family is empty for an opaque id such as `AC_1`, stamp the correct generic type instead of adding a vendor/site heuristic to Rust.
