# In-app agent model routing (Codex relay)

Routing for **Agent assist** (`POST /api/agent/chat` → `tools/codex-chat-relay` → `codex exec`).

## Policy

| Context / trigger | Agent | Model | Sandbox |
|-------------------|-------|-------|---------|
| `/csv` or CSV keywords | `csv_data_assistant` | gpt-5.4-mini | workspace-write |
| `/model`, `/sql-fdd`, FDD/assignment keywords | `fdd_model_assistant` | gpt-5.4-mini | workspace-write (high reasoning) |
| `/bacnet`, `/haystack`, deploy, auth | `openfdd_retrofit_orchestrator` | gpt-5.4-mini | workspace-write |
| Single test/lint/HTTP error | `simple_test_triage` | gpt-5.4-mini | read-only |
| PR / release / security review | `release_risk_reviewer` or spawn review skills | gpt-5.4-mini | read-only |

## Skills (research_review_agent_skills v1)

Installed under `.agents/skills/` (Codex) and `.cursor/skills/` (Cursor). Invoke explicitly in chat or agent instructions:

- `$codebase-research-pass` — before large CSV/model changes
- `$spec-contract-compliance-review` — trace FDD requirements to code
- `$multi-agent-pr-review` — pre-merge review
- `$release-readiness-review` — ship checklist

Research-pack agents in `.codex/agents/`: `codebase-mapper`, `correctness-reviewer`, `security-reliability-reviewer`, `test-verifier`, `release-risk-reviewer`, etc.

## Open-FDD agents

| File | Role |
|------|------|
| `csv-data-assistant.toml` | CSV fusion, MCP import, toolshed |
| `fdd-model-assistant.toml` | Model, assignments, SQL FDD |
| `openfdd-retrofit-orchestrator.toml` | Edge, drivers, releases |
| `simple-test-triage.toml` | Quick failures |

Config: `.codex/config.toml` — MCP `openfdd`, `[agents]` thread limits.
