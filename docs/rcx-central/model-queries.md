# Model queries (RCx Central → OpenFDD Edge + local TTL mirror)

OpenFDD RCx Central reuses the **same read-only Edge REST APIs** as the Edge operator React **Data model** tab. RCx Central does not scrape the React UI.

**Local BRICK SPARQL:** `POST /api/central/model/sync-ttl/{site_id}` fetches Edge `model.json`, builds TTL with the same `ttl_service` as Edge, and stores it under `portfolio/data/sites/{site_id}/model/data_model.ttl`. Central runs SPARQL locally (rdflib). Optionally calls Edge `POST /api/model/sync-ttl` first so on-site TTL stays aligned when the Edge image is current.

## Primary endpoints

| Method | Edge path | Purpose |
|--------|-----------|---------|
| GET | `/api/model/tree` | Equipment + points (BRICK roles, timeseries columns) |
| GET | `/api/model/health` | Point/equipment counts, model issues |
| GET | `/api/model/sparql/predefined` | Prebuilt SPARQL query list |
| POST | `/api/model/sparql` | Run SPARQL (`{"query": "..."}`) |
| GET | `/api/model/fdd-query-presets` | FDD commissioning query presets |
| GET | `/api/model/fdd-query-presets/{id}` | Run preset by id |
| GET | `/api/model/ttl?save=false` | Turtle text (used by Central TTL mirror) |
| POST | `/api/model/sync-ttl` | Regenerate TTL on Edge from `model.json` |

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
| POST | `/api/central/model/remediate/{site_id}` | Edge model fix + TTL sync + Central mirror |
| POST | `/api/central/model/sync-ttl/{site_id}` | Edge sync + pull TTL to Central |
| GET | `/api/central/model/ttl/{site_id}` | Mirror status (bytes, synced_at) |
| GET | `/api/central/model/sparql/predefined/{site_id}` | Edge catalog + mirror status |
| POST | `/api/central/model/sparql/{site_id}` | Local SPARQL (`query` or `query_id`) |
| GET | `/api/central/model/sparql/validate/{site_id}` | AHU/VAV/site count sanity checks |
| POST | `/api/central/rcx/preview` |

Edge model mutations use integrator auth via remediate; SPARQL on Central is read-only.

## FDD preset ids (Edge parity)

Same as React `DataModelSparqlPanel` FDD buttons:

`rules_to_equipment`, `rules_to_sensors`, `rules_to_bacnet_devices`, `equipment_to_points`, `ahus_vavs_zones`, `missing_rule_bindings`, `points_by_bacnet_device`, `sensor_classes_used_by_fdd`, `rule_coverage_by_equipment_type`, `orphan_points`

Dash **Local BRICK SPARQL** buttons call Central paths above (mirrored TTL).

## BRICK typing (do not mis-count AHUs/VAVs)

Many sites (including Acme) set **`brick_type`** (`AHU`, `VAV`) without `equipment_type`. Presets and mechanical narrative use `equipment_classify` — not `equipment_type` alone.

After `model.json` changes on Edge, **sync TTL** (`POST /api/central/model/sync-ttl/{site_id}` or remediate) so SPARQL predefined queries (`Air_Handling_Unit`, `Variable_Air_Volume_Box`) match equipment counts.

Packaged rooftop air handlers feeding VAVs should be modeled as **`brick_type: AHU`** even when the legacy BACnet name contains "RTU".
