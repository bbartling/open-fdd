---
title: How-to Guides
nav_order: 10
has_children: true
---

# How-to Guides

Recipes for **`pip install open-fdd`**, **`[engine]`** extras, releases, skills-based scaffolding, and embedding **`RuleRunner`** on **pandas**.

**Full platform** (data model, APIs, compose, dashboards): **[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**

---

## Engine and agent

- [Skills and agent shell](skills_and_agent) — `openfdd.toml`, `skills/`, Codex CLI shell, `workspace/` layout.
- [PyPI releases (open-fdd)](openfdd_engine_pypi) — tags, trusted publishing, `twine check`.
- [The optional openfdd-engine package](openfdd_engine) — `openfdd_engine` vs `open_fdd.engine`.
- [Engine-only deployment and external IoT pipelines](engine_only_iot) — `RuleRunner` on DataFrames.
- [Verification](verification) — focused pytest for expressions and cookbook regressions.
- [Cloning and porting](cloning_and_porting) — portable rules and envs.
- [Operations (engine)](operations) — CI and scheduling notes.
- [Danger zone](danger_zone) — expression safety and sharp edges.
- [Quick reference](quick_reference) — imports and common commands.

## Historical desktop stack (reference)

- [Desktop app (retired monolith)](desktop_app)
- [Agent & operator playbook (bridge + MCP)](agent_operator_playbook)
- [Toolshed (retired)](toolshed)
- [Open-FDD + Easy-ASO test bench](openfdd_easy_aso_bench)

Published site: **[bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/)**
