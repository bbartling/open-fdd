---
name: openfdd-fdd-commissioning-agent
description: "Commission building FDD via MCP — model query, equipment context, rule recommendations, lint/test before save."
---

# FDD commissioning agent

Use MCP prompt `commission_building_fdd` or tool chain:

1. `search_model` / `get_equipment_context`
2. `list_fault_catalog` — never invent codes
3. `recommend_rules_for_equipment`
4. `search_rule_cookbook`
5. `draft_arrow_rule` → `lint_rule` → human → `save_rule`

Bind points on bridge Data Model tab before saving rules.
