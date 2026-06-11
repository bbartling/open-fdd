---
name: openfdd-rule-authoring-agent
description: "Author Arrow-native apply_faults_arrow rules from the expression cookbook via MCP Rule Lab APIs."
---

# Rule authoring agent

- Cookbook: `docs/rule-cookbook/expression-cookbook.md`
- Draft: `draft_arrow_rule` (does not persist)
- Validate: `lint_rule`, bridge `/api/playground/test-rule`
- Save: `save_rule` with `human_approved=true` only

New rules must use `apply_faults_arrow(table, cfg, context)` — not `evaluate(row, cfg)`.
