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
| GET | `/api/central/mechanical-summary/{site_id}` |
| GET | `/api/central/fdd-analytics/{site_id}` |
| POST | `/api/central/rcx/preview` |

All calls are **read-only** toward Edge.
