# OpenFDD RCx Central — current state

Branch: `feature/rcx-central-edge-analytics-docx`  
Updated: 2026-05-30

## Product names

| User-facing | Internal path |
|-------------|----------------|
| **OpenFDD Edge** | `workspace/`, `docker/`, GHCR images |
| **OpenFDD RCx Central** | `portfolio/` (Dash + Central API) |

## Entrypoints

| Service | Command | Port |
|---------|---------|------|
| RCx Central Dash | `python -m portfolio.dash` / `./scripts/run_portfolio_dash.sh` | 8050 |
| RCx Central API | `./scripts/run_central_api.sh` → `python scripts/run_central_api.py` | 8060 |
| Docker (both) | `./scripts/run_rcx_central_docker.sh` | 8050, 8060 |

## Central API (new/changed)

- `GET/POST/PUT/DELETE /api/central/edges`, `POST /api/central/edges/test`
- `GET /api/central/mechanical-summary/{site_id}`
- `GET /api/central/fdd-analytics/{site_id}`
- `POST /api/central/rcx/preview`, `/charts/preview`, `/report`
- `POST /api/central/rcx/report-legacy` (backward compatible)

## Edge REST (read-only)

Model: `/api/model/tree`, `/api/model/health`, SPARQL, `/api/model/fdd-query-presets`  
Trends: `/api/timeseries/readings`, `/api/timeseries/series`  
Analytics: `/api/analytics/overview`, `/api/analytics/faults`  
Faults: `/api/faults/status`  
Collect: `/api/building/portfolio-rollup`

## Dash UI tabs

Overview · Edge Connections · Mechanical Summary · FDD Analytics · Trend Explorer · RCx Report Builder · Validation Runs · Settings

Header: **OpenFDD RCx Central**

## RCx / charts

- `portfolio/central/chart_preview.py` — matplotlib base64 previews, fault overlay bands from timeseries fault flags
- `portfolio/central/trend_charts.py` — role→column mapping, trend fetch
- `portfolio/central/fdd_analytics.py` — rules + chart packs
- `open_fdd/reports/rcx_docx.py` — DOCX when installed

## Docker

`docker/rcx-central/` — Dockerfile, compose, volumes `rcx-central-data`, `rcx-central-config`  
Smoke: `scripts/test_rcx_central_docker.sh`, `scripts/test_rcx_central_docker.ps1`

## Tests

`tests/portfolio/test_central.py`, `test_edge_registry.py`, `test_chart_preview.py`

## Remaining gaps

- GHCR publish for `openfdd-rcx-central` image tag
- Trend Explorer tab (placeholder; Overview Plotly charts use local CSV collect)
- Live ACME opt-in manual workflow doc section in CI
- Deeper equipment-tree scope in RCx builder UI
- More chart types (economizer, VAV worst zones)

## Recommended next PR

Publish RCx Central image + expand chart catalog + equipment-tree report scope.
