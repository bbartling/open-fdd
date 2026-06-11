---
name: openfdd-portfolio-agent
description: "Central portfolio agent over Tailscale — morning check, multi-site rollup, no edge MCP required."
---

# Open-FDD portfolio agent

## Registry

Edit `portfolio/sites.json` (gitignored secrets on live machines). Example:

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

## Workflow

1. `portfolio_morning_check` prompt or `portfolio_rollup()`
2. Per-site: `building_agent_checkin` (batch off by default)
3. `get_tuning_brief` → `preview_fdd_tuning` → human approval → `apply_fdd_tuning`

Memory: `workspace/MEMORY.md` (live, gitignored) — bootstrap from `workspace/MEMORY.md.example`.
