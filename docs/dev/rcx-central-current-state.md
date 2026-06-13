# OpenFDD RCx Central — current state

Updated: 2026-06-13  
Branches: `feature/rcx-central-overview-ui` (#298), `fix/edge-dashboard-bridge` (#299)

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
- `GET /api/central/fdd-preset/{site_id}/{preset_id}` — Edge FDD preset proxy
- `GET /api/central/mechanical-summary/{site_id}`
- `POST /api/central/rcx/preview`, `/charts/preview`, `/report`

## Edge REST (read-only, shared with Data Model tab)

Model: `/api/model/tree`, `/api/model/health`, SPARQL, `/api/model/fdd-query-presets/{id}`  
Trends: `/api/timeseries/readings`  
Analytics: `/api/analytics/faults`  
Faults: `/api/faults/status`, `/api/faults/catalog`

## Dash UI tabs

**Dashboard** (unified) · **Edge Connections**

Dashboard sections: fault mix + legend, building summary, P8 KPI (+ chart if overrides), FDD rules table, **FDD/BRICK preset buttons** (Edge parity), RCx report builder.

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

- GHCR publish for `openfdd-rcx-central` image
- Summarize HVAC SPARQL buttons on Dash (FDD presets done; raw SPARQL optional)
- Deeper equipment-tree scope in RCx builder UI
