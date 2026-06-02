---
title: How-to Guides
nav_order: 10
has_children: true
---

# How-to Guides

Recipes for **`pip install open-fdd`**, **`[engine]`** extras, releases, and embedding **`RuleRunner`** on **pandas**.

---

## Agent-maintained stack (git checkout)

- [Operator dashboard (Rule Lab)](operator_dashboard) — `./scripts/openfdd_stack.sh up`, Rule Lab, BACnet, host stats.
- [Edge deploy (Docker)](../edge_deploy_docker) — Acme / field VMs.
- [Rule Lab — Python storage & shared editing](rule_lab_storage) — `rules_py/`, browser save flow, AI `rules.save`, FDD loop.
- [Skills and agent shell](skills_and_agent) — `openfdd.toml`, Codex REPL, workspace cron/wake, memory, tests.
- [Agent & operator playbook](agent_operator_playbook) — bridge + MCP routes when `workspace/api` is generated.
- [Desktop app (retired)](desktop_app) — historical gateway/MCP/UI reference only.

---

## Engine

- [PyPI releases (open-fdd)](openfdd_engine_pypi) — tags, trusted publishing, `twine check`.
- [The optional openfdd-engine package](openfdd_engine) — `openfdd_engine` vs `open_fdd.engine`.
- [Engine-only deployment and external IoT pipelines](engine_only_iot) — `RuleRunner` on DataFrames.
- [Verification](verification) — focused pytest for expressions and cookbook regressions.
- [Cloning and porting](cloning_and_porting) — portable rules and envs.
- [Operations (engine)](operations) — CI and scheduling notes.
- [Danger zone](danger_zone) — expression safety and sharp edges.
- [Quick reference](quick_reference) — imports and common commands.

Published site: **[bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/)**
