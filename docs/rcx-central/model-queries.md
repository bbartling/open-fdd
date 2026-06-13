# Model queries (RCx Central → OpenFDD Edge)

OpenFDD RCx Central reuses the **same read-only Edge REST APIs** as the Edge operator React **Data model** tab. RCx Central does not scrape the React UI.

## Primary endpoints

| Method | Edge path | Purpose |
|--------|-----------|---------|
| GET | `/api/model/tree` | Equipment + points (BRICK roles, timeseries columns) |
| GET | `/api/model/health` | Point/equipment counts, model issues |
| GET | `/api/model/sparql/predefined` | Prebuilt SPARQL query list |
| POST | `/api/model/sparql` | Run SPARQL (`{"query": "..."}`) |
| GET | `/api/model/fdd-query-presets` | FDD commissioning query presets |
| GET | `/api/model/fdd-query-presets/{id}` | Run preset by id |

## Trends (matplotlib preview + fault overlays)

| Method | Edge path | Purpose |
|--------|-----------|---------|
| GET | `/api/timeseries/series?site_id=` | Plottable columns per site |
| GET | `/api/timeseries/readings?site_id=&columns=&hours=` | Trend samples + optional FDD fault flags |

RCx Central maps BRICK **point roles** (e.g. `supply_air_temperature`) to historian columns via `/api/model/tree`, then calls `/api/timeseries/readings` with `include_faults=true` for overlay bands.

## Analytics

| Method | Edge path | Purpose |
|--------|-----------|---------|
| GET | `/api/analytics/overview` | KPIs, fault hours by severity/equipment |
| GET | `/api/analytics/faults?hours=` | Fault rows for selected window |
| GET | `/api/analytics/model-health` | Stale/missing roles |

## RCx Central API wrappers

| Method | Central path |
|--------|----------------|
| GET | `/api/central/overview/{site_id}` |
| GET | `/api/central/mechanical-summary/{site_id}` |
| GET | `/api/central/fdd-analytics/{site_id}` |
| GET | `/api/central/fdd-preset/{site_id}/{preset_id}` |
| POST | `/api/central/rcx/preview` |

All calls are **read-only** toward Edge.

## FDD preset ids (Edge parity)

Same as React `DataModelSparqlPanel` FDD buttons:

`rules_to_equipment`, `rules_to_sensors`, `rules_to_bacnet_devices`, `equipment_to_points`, `ahus_vavs_zones`, `missing_rule_bindings`, `points_by_bacnet_device`, `sensor_classes_used_by_fdd`, `rule_coverage_by_equipment_type`, `orphan_points`

## BRICK typing (do not mis-count AHUs/VAVs)

Many sites (including Acme) set **`brick_type`** (`AHU`, `VAV`) without `equipment_type`. Presets and mechanical narrative use `equipment_classify` — not `equipment_type` alone.

After `model.json` changes on Edge, **sync TTL** (`ttl_service.sync`) so SPARQL predefined queries (`Air_Handling_Unit`, `Variable_Air_Volume_Box`) match equipment counts.

Packaged rooftop air handlers feeding VAVs should be modeled as **`brick_type: AHU`** even when the legacy BACnet name contains "RTU".
