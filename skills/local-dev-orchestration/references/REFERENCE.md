# Local orchestration — reference

Legacy: `scripts/start-local.sh`, `scripts/start-local.ps1`.

Bootstrap fields (legacy `open_fdd/gateway/openfdd_agent_context.py`):

- `bridge_base`, `mcp_rest_base`, `ui_public_base`, `desktop_data_dir`
- `endpoints.*` health, openapi, sites, plots, agent chat
- `toolshed.scratch_rel` → `toolshed/scratch`

Env: `OFDD_BRIDGE_URL`, `OFDD_UI_PUBLIC_BASE`, `OFDD_MCP_REST_BASE`, `OFDD_AGENT_BOOTSTRAP_FILE`, `OFDD_MCP_RAG_INDEX_MODE` (auto|always|skip).
