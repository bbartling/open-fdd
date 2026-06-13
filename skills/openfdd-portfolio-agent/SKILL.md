---
name: openfdd-portfolio-agent
description: "Central portfolio agent over Tailscale — RCx Central API/Dash, morning check, multi-site rollup, no edge MCP required."
---

# Open-FDD portfolio agent

## Registry

Edit `portfolio/config/sites.json` (credentials in `portfolio/config/credentials.json` on live machines). Example:

```json
{
  "sites": [
    {
      "site_id": "acme",
      "name": "Acme GL36 Lab",
      "base_url": "http://100.122.106.124",
      "username": "integrator"
    }
  ]
}
```

Set `OFDD_MCP_MODE=portfolio` and `OFDD_PORTFOLIO_SITES_PATH` when running MCP.

## RCx Central (preferred for analyst UI)

Not MCP — separate HTTP services:

```bash
./scripts/run_central_api.sh    # :8060
./scripts/run_portfolio_dash.sh # :8050
```

- Dash: Edge Connections → Dashboard → FDD preset buttons, building summary, RCx DOCX
- API smoke: `curl http://127.0.0.1:8060/api/central/overview/acme`
- Agent doc: `docs/agent-skills/rcx-central-dash-agent.md`

## MCP workflow

1. `portfolio_morning_check` prompt or `portfolio_rollup()`
2. Per-site: `building_agent_checkin` (batch off by default)
3. `get_tuning_brief` → `preview_fdd_tuning` → human approval → `apply_fdd_tuning`

## Fault codes

Fixed letter-suffix codes only. Short labels: `docs/fault-codes/short-lookup.md`, `portfolio/central/fault_code_lookup.py`. Live: `GET /api/faults/catalog` on Edge.

## BRICK model

Use `brick_type` on equipment (`AHU`, `VAV`). Sync TTL after model edits so SPARQL HVAC counts work. See `docs/rcx-central/model-queries.md`.

Memory: `workspace/MEMORY.md` (live, gitignored) — bootstrap from `workspace/MEMORY.md.example`.
