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

## When to use

- Building a zip / sidecar `column_map` / Haystack `points`
- Overview tables, RCx plots, Inspect overlay, or health matrices are empty
- Agent is guessing equipment type from folder names

## Rules

1. Empty analytics = **missing roles in the zip**, not a broken FDD engine. Map in preprocess.
2. Stamp `equipType` (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`). `rtu`→AHU; `heatPump`→HP; UV/FCU air-side→ahu; chillers→chwPlant.
3. Haystack names in `points` translate via `haystack_point_to_role`. Do not invent a second product vocabulary.
4. Motor ≠ compressor ≠ valve. Status/cmd before amps. Never CHW pump or `clg_valve_pct` as compressor proof. Never motor hours from leave temp.
5. Weather lives at `{building}/weather/` with `web-outside-air-temp` → `web_oa_t`. Lat/lon in preprocess. `prefer_web_oat`.
6. `timestamp_utc` is RFC3339 (`Z` or `+00:00`). String `"equip": "AHU_1"` is metadata.
7. Import with existing `POST /api/csv/import/package` + MCP `openfdd_csv_import_*` / `openfdd_csv_package_append`. For **streaming sim** on Liberty B50: host script `scripts/csv_flood_afdd_routine_sim.py` (append + AFDD routine patches). Do **not** implement SCAFFOLD `mapping_suggest` / `package_preflight` this cycle.
8. No vendor/city hardcoding in product. Gold ids: `AHU_1` / `VAV_1` / `CHW_1` / `weather/`.

## Anti-patterns

- Patching SQL because a plot is empty
- Porting vibe19 Streamlit Data Model into the SPA
- Duplicating this skill into `~/.cursor/skills/`
