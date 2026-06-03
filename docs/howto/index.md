---
title: How-to Guides
nav_order: 10
has_children: true
---

# How-to guides

**Deploy and operate** the edge stack first; PyPI engine how-tos are listed last.

---

## Deploy & operate

| Guide | Topic |
|-------|--------|
| [Operator dashboard](operator_dashboard) | Rule Lab, `./scripts/openfdd_stack.sh` |
| [Edge deploy (Docker)](../edge_deploy_docker) | Acme / field VMs |
| [Rule Lab storage](rule_lab_storage) | `rules_py/`, bindings, batch |
| [Ollama hardware](ollama_edge_deploy) | GPU/CPU install paths |
| [Skills and agent shell](skills_and_agent) | Cursor/Codex, `openfdd.toml`, cron |
| [Agent playbook](agent_operator_playbook) | Bridge + MCP tools |
| [Verification](verification) | pytest focus |

---

## Engine (PyPI / offline)

| Guide | Topic |
|-------|--------|
| [PyPI releases](openfdd_engine_pypi) | Tags, publishing |
| [Engine-only IoT](engine_only_iot) | `RuleRunner` on DataFrames |
| [Quick reference](quick_reference) | Imports |
| [Cloning and porting](cloning_and_porting) | Portable YAML |
| [Danger zone](danger_zone) | Expression safety |

Historical: [Desktop app (retired)](desktop_app).
