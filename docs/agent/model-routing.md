---
title: External agent routing
parent: External agents
nav_order: 3
---

# External agent routing (Codex / Cursor)

Routing for **external** agents configured in `.codex/` and `.cursor/agents/`. Open-FDD does not invoke these from the dashboard.

## Policy

| Context / trigger | Agent | Notes |
|-------------------|-------|-------|
| CSV import, fusion, historian | `csv_data_assistant` | MCP CSV tools |
| Model, assignments, SQL FDD | `fdd_model_assistant` | MCP model + FDD |
| Deploy, auth, drivers, releases | `openfdd_retrofit_orchestrator` | Complex retrofit |
| Single test/lint/HTTP error | `simple_test_triage` | Quick triage |
| PR / release review | Review skills in `.agents/skills/` | Portable |

## Skills (`.agents/skills/`)

Portable review skills — not part of edge runtime:

- `$codebase-research-pass`
- `$spec-contract-compliance-review`
- `$multi-agent-pr-review`
- `$release-readiness-review`
- `$performance-ab-benchmark-review`
- `$architecture-design-review`
- `$external-source-research`

## Open-FDD Codex agents (`.codex/agents/`)

| File | Role |
|------|------|
| `csv-data-assistant.toml` | CSV fusion, MCP import, toolshed |
| `fdd-model-assistant.toml` | Model, assignments, SQL FDD |
| `openfdd-retrofit-orchestrator.toml` | Edge, drivers, releases |
| `simple-test-triage.toml` | Quick failures |

Config: `.codex/config.toml` — MCP `openfdd`, `[agents]` thread limits.

## Cursor agents (`.cursor/agents/`)

Mirror roles for Cursor IDE — external development agents only. See [../mcp-agents/cursor-openclaw.md](../mcp-agents/cursor-openclaw.md).
