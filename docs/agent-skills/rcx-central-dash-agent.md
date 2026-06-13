# RCx Central Dash — agent guide

For Cursor/Codex agents working on **OpenFDD RCx Central** (`portfolio/`) — analyst Dash + Central API over read-only Edge REST.

## Runtime stack (benserver / analyst workstation)

| Service | Script | Port | Bind |
|---------|--------|------|------|
| RCx Central API | `./scripts/run_central_api.sh` | 8060 | `0.0.0.0` (`OPENFDD_CENTRAL_API_HOST`) |
| RCx Central Dash | `./scripts/run_portfolio_dash.sh` | 8050 | `0.0.0.0` (`OPENFDD_RCX_DASH_HOST`) |

Env: `OPENFDD_CENTRAL_API_URL=http://127.0.0.1:8060` (Dash → API). LAN access: `sudo ./scripts/open_rcx_central_lan_ports.sh` (UFW 8050+8060).

**Not** the operator bridge (`:8765`) — RCx Central polls Edge sites via Tailscale/LAN URLs in `portfolio/config/sites.json`.

## Dash UI (2026-06)

Single **Dashboard** tab (faults, building summary, FDD rules, preset buttons, RCx report) + **Edge Connections** tab.

| Area | Data source |
|------|-------------|
| Fault pie + legend | `fault_code_lookup.py` + live/CSV faults |
| Building summary | `build_mechanical_narrative()` → Edge FDD presets |
| FDD rules table | `GET /api/central/fdd-analytics/{site_id}` |
| FDD preset buttons | `GET /api/central/fdd-preset/{site_id}/{preset_id}` → same as Edge Data Model tab |
| P8 overrides | KPI count always; chart only when overrides present |
| RCx DOCX | `POST /api/central/rcx/report` |

## Edge parity (Data Model tab)

RCx Central must **not** scrape React. Use Edge REST:

- `GET /api/model/fdd-query-presets` + `GET /api/model/fdd-query-presets/{id}`
- `GET /api/model/sparql/predefined` + `POST /api/model/sparql`
- `GET /api/model/health`, `GET /api/model/tree`

Preset ids: `rules_to_equipment`, `rules_to_sensors`, `ahus_vavs_zones`, `missing_rule_bindings`, `orphan_points`, `rule_coverage_by_equipment_type`, etc. — see `portfolio/central/fdd_preset_catalog.py`.

## BRICK equipment typing (common bug)

Acme and many sites store types in **`brick_type`** (`AHU`, `VAV`), not `equipment_type`.

- Count/classify with `portfolio/central/equipment_classify.py` (mirrors `workspace/api/openfdd_bridge/equipment_classify.py`).
- TTL sync maps short types → Brick classes (`AHU` → `Air_Handling_Unit`, `VAV` → `Variable_Air_Volume_Box`) in `ttl_service.py`.
- After model.json edits on Edge: **sync TTL** before SPARQL HVAC buttons return counts.
- Packaged rooftop serving VAVs: prefer **`brick_type: AHU`** and display name `AHU 01` (not `Rtu 01`) when it is a full air handler.

## Fault codes (stable labels)

| Layer | Path |
|-------|------|
| Docs table | `docs/fault-codes/short-lookup.md` |
| Dash lookup | `portfolio/central/fault_code_lookup.py` |
| Edge catalog | `GET /api/faults/catalog` · `workspace/api/openfdd_bridge/fault_catalog.py` |

Never invent codes. Letter suffix only (`VAV-C`, not `VAV-03`).

## Central API routes (agent smoke)

```bash
curl -s http://127.0.0.1:8060/health
curl -s http://127.0.0.1:8060/api/central/overview/acme
curl -s "http://127.0.0.1:8060/api/central/fdd-analytics/acme?hours=24"
curl -s http://127.0.0.1:8060/api/central/fdd-preset/acme/ahus_vavs_zones
```

## Tests

```bash
pytest tests/portfolio/ tests/scripts/test_rcx_overnight_patch_cycle.py
pytest tests/workspace_bridge/test_fdd_query_presets.py
```

## PRs (typical split)

- **Edge bridge + TTL + model fixes** → `fix/edge-dashboard-bridge` (#299)
- **RCx Dash / portfolio only** → `feature/rcx-central-overview-ui` (#298)

## Related

- [Overnight patch cycle](rcx-central-overnight-patch-cycle.md)
- [Model queries](../rcx-central/model-queries.md)
- [MCP server](../ai/mcp-server.md) — portfolio mode vs RCx Central HTTP API
