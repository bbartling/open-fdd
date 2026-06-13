# AI agent workflow vs runtime use

## Three agent surfaces

| Surface | Port | Use when |
|---------|------|----------|
| **OpenFDD Edge** (bridge) | 8765 / :80 Caddy | Rule Lab, BACnet, Data Model SPARQL, live FDD |
| **OpenFDD RCx Central** | 8050 Dash, 8060 API | Multi-site analyst dashboard, RCx DOCX, Edge registry |
| **OpenFDD MCP** | 8090 | Cursor/Codex tools over bridge or `portfolio/sites.json` |

Acme production edge runs **without** MCP (`enable_mcp: false`). Use **RCx Central API** or **portfolio MCP** against `http://100.122.106.124` (Tailscale).

## Runtime analyst (no git clone)

1. `docker compose -f docker/rcx-central/docker-compose.yml up` **or** `./scripts/run_central_api.sh` + `./scripts/run_portfolio_dash.sh`
2. Open http://localhost:8050 (LAN: `sudo ./scripts/open_rcx_central_lan_ports.sh` on benserver)
3. **Edge Connections** → add Acme URL → Test → Save
4. **Dashboard** → select building → verify building summary (AHU/VAV counts), FDD preset buttons, fault pie descriptions
5. **RCx report** → Preview → Generate DOCX

Kill containers when done. Registry in Docker volume `rcx-central-config`.

## Developer / coding agent (git working tree)

Use Cursor or Codex against `open-fdd`. Read:

- [RCx Central Dash agent guide](../agent-skills/rcx-central-dash-agent.md)
- [Overnight patch cycle](../agent-skills/rcx-central-overnight-patch-cycle.md)

Key modules: `portfolio/dash/overview_tab.py`, `portfolio/central/mechanical_narrative.py`, `portfolio/central/fault_code_lookup.py`, `workspace/api/openfdd_bridge/fdd_query_presets.py`, `ttl_service.py`.

After doc changes consumed by MCP RAG: `./scripts/build_mcp_rag_index.sh` (optional on benserver).

## Model / SPARQL validation (Acme)

1. Confirm `model.json` equipment uses `brick_type` (`AHU`, `VAV`) — not only legacy `equipment_type`
2. Sync TTL on Edge (Data Model tab or bridge restart)
3. Edge UI: **Summarize HVAC → AHUs / VAV boxes** must return non-zero for Acme lab
4. RCx Dash: **AHUs / VAVs / Zones** preset → same row counts as Edge

## Secrets

- Never commit `portfolio/config/credentials.json` or passwords in `sites.json`
- Env: `OFDD_AGENT_PASSWORD`, per-site credentials in config store
- Live ACME tests: `OPENFDD_LIVE_ACME=1` only when explicitly requested

## Model routing (test triage)

See `AGENTS.md` — classify CI failures as SIMPLE vs COMPLEX before processing.
