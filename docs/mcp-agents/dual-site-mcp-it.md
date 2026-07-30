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
| **A** Accuracy | `openfdd_fdd_accuracy_snapshot` for Active `BUILDING_50` ≠ `BUILDING_100` (distinct equipment / FAULT totals). |
| **B** Historian | `openfdd_historian_query` with `site_id` / building filter returns scoped rows only. |
| **C** Findings | After Eng Findings generate (or `openfdd_reports_draft` with `kind=engineering_findings`), `GET /api/reports/engineering-findings` → **200**. |

## Pointers (OFDD-MCP-CTX)

Call `openfdd_agent_context_pointers` — read-only companion paths; **never** IDF surgery in openfdd-mcp.

See [`companion-wattlab-energyplus.md`](companion-wattlab-energyplus.md).
