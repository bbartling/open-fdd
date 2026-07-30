---
title: Dual-site MCP IT (Liberty / OFDD-MCP-IT)
parent: MCP agents
nav_order: 35
---

# Dual-site MCP integration checklist (OFDD-MCP-IT)

Use after csv(+caddy) stack is up on tip `sha-*` with Liberty B50 + B100 loaded.

## ENH-13h — A / B / C

| Case | Assert |
|------|--------|
| **A** Sites distinct | `openfdd_datasets` (or equipment list) shows distinct canonical IDs `BUILDING_50` vs `BUILDING_100`. Note: `openfdd_fdd_accuracy_snapshot` is **global** registry/result parity — not per-site. |
| **B** Historian | `openfdd_historian_query` with `site_id=BUILDING_50` vs `BUILDING_100` returns scoped rows only. |
| **C** Findings | With `OPENFDD_MCP_ALLOW_WRITES=1` on the MCP server, call `openfdd_reports_draft` with `confirm:true` and `kind=engineering_findings` (or Eng Findings UI generate); then `GET /api/reports/engineering-findings` → **200**. |

## Pointers (OFDD-MCP-CTX)

Call `openfdd_agent_context_pointers` — read-only companion paths; **never** IDF surgery in openfdd-mcp.

See [`companion-wattlab-energyplus.md`](companion-wattlab-energyplus.md).
