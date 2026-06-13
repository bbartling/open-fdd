# OpenFDD RCx Central — current state

Updated: 2026-05-30  
Branches: `feature/rcx-central-overview-ui` (#298)  
**Status:** Local TTL mirror + SPARQL on Central; benserver sign-off before Docker GHCR publish.

## Product names

| User-facing | Internal path |
|-------------|----------------|
| **OpenFDD Edge** | `workspace/`, `docker/`, GHCR images |
| **OpenFDD RCx Central** | `portfolio/` (Dash + Central API) |

## Entrypoints

| Service | Command | Port | Bind default |
|---------|---------|------|--------------|
| RCx Central Dash | `./scripts/run_portfolio_dash.sh` | 8050 | `0.0.0.0` |
| RCx Central API | `./scripts/run_central_api.sh` | 8060 | `0.0.0.0` |
| Docker (both) | `docker/rcx-central/docker-compose.yml` | 8050, 8060 | |

LAN firewall (benserver): `sudo ./scripts/open_rcx_central_lan_ports.sh`

## Central API

- `GET/POST/PUT/DELETE /api/central/edges`, `POST /api/central/edges/test`
- `GET /api/central/overview/{site_id}` — KPIs, fault pie, mechanical narrative, P8
- `GET /api/central/fdd-analytics/{site_id}` — rules table + descriptions
- `GET /api/central/fdd-preset/{site_id}/{preset_id}` — Edge FDD preset proxy + Central enrichment
- `POST /api/central/model/remediate/{site_id}` — equipment types, BACnet metadata, Edge TTL sync, Central mirror
- `POST /api/central/model/sync-ttl/{site_id}` — pull `data_model.ttl` to `portfolio/data/sites/{site_id}/model/`
- `GET /api/central/model/sparql/validate/{site_id}` — local AHU/VAV/site SPARQL counts
- `POST /api/central/model/sparql/{site_id}` — read-only SPARQL on mirrored TTL
- `GET /api/central/mechanical-summary/{site_id}`
- `GET /api/central/model-tree/{site_id}` — on-demand BRICK tree (lazy; not on auto-refresh)
- `GET /api/central/rcx/points/{site_id}` — BACnet point catalog for Report Builder
- `POST /api/central/rcx/preview`, `/charts/preview`, `/report`

## Edge REST (read-only, shared with Data Model tab)

Model: `/api/model/tree`, `/api/model/health`, SPARQL, `/api/model/fdd-query-presets/{id}`  
Trends: `/api/timeseries/readings`  
Analytics: `/api/analytics/faults`  
Faults: `/api/faults/status`, `/api/faults/catalog`

## Dash UI tabs

**Dashboard** · **Report Builder** · **Edge Connections**

Dashboard: fault mix + legend, building summary, P8 KPI, FDD rules (lazy load), FDD/BRICK preset buttons, **local SPARQL** (TTL mirror).  
Report Builder: 3-step wizard — building/time → charts & sections → custom points → preview DOCX.  
Edge data fetched on demand (not with dashboard load).

## Pre-Docker owner checklist (benserver :8050)

1. Dashboard loads in under 5s without hanging on model tree.
2. **Load full BRICK model** and **Load FDD rules** buttons work when clicked.
3. Report Builder: load catalog → preview charts → generate DOCX for Acme.
4. Fault overlays visible on trend previews when enabled.
5. Sign off here before `docker/rcx-central` image rebuild or `RCX_ALLOW_PUBLISH=1`.

## BRICK model notes (agents)

- Classify equipment with `brick_type` **and** `equipment_type` — see `equipment_classify.py`
- TTL maps `AHU`/`VAV` → Brick schema classes for SPARQL HVAC queries
- Acme roof unit: `brick_type: AHU`, name `AHU 01` (not `Rtu 01` in new models)

## Fault codes

- Stable short labels: `docs/fault-codes/short-lookup.md`, `portfolio/central/fault_code_lookup.py`
- Full catalog: `GET /api/faults/catalog` on Edge

## Agent docs

- [RCx Central Dash agent guide](../agent-skills/rcx-central-dash-agent.md)
- [AI agent workflow](../rcx-central/ai-agent-workflow.md)
- [MCP server](../ai/mcp-server.md)

## Tests

`pytest tests/portfolio/` · `tests/workspace_bridge/test_fdd_query_presets.py`

## Remaining gaps

- **Owner Dash sign-off** on benserver before Docker GHCR publish
- GHCR publish for `openfdd-rcx-central` image (gated: `RCX_ALLOW_PUBLISH=1`)
- Optional OpenAI insights hook (templates used today)
- True Edge `start`/`end` bounded timeseries (hours lookback used for now)
- Summarize HVAC SPARQL buttons on Dash — **done** (local TTL mirror on Central)
