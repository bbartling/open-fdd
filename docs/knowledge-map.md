---
title: Knowledge Map
nav_order: 21
---

# Knowledge Map

*A map of where information lives. For agents and humans.*

---

## Rule authoring

| Need | Where |
|------|-------|
| Rule recipes (AHU, chiller, VAV, weather) | [Expression Rule Cookbook]({{ "expression_rule_cookbook" | relative_url }}) |
| Rule types, YAML structure | [Configuration]({{ "configuration" | relative_url }}) |
| BRICK naming convention | [Expression Rule Cookbook]({{ "expression_rule_cookbook" | relative_url }}) — BRICK naming section |
| Built-in rule types (bounds, flatline, hunting, etc.) | [Bounds]({{ "bounds_rule" | relative_url }}), [Flatline]({{ "flatline_rule" | relative_url }}), [Hunting]({{ "hunting_rule" | relative_url }}), [OA Fraction]({{ "oa_fraction_rule" | relative_url }}), [ERV Efficiency]({{ "erv_efficiency_rule" | relative_url }}) |

---

## Brick & column resolution

| Need | Where |
|------|-------|
| Brick TTL → column_map | [Data Model & Brick]({{ "data_model" | relative_url }}), [API Reference]({{ "api_reference" | relative_url }}) — brick_resolver |
| resolve_from_ttl, get_equipment_types_from_ttl | [API Reference]({{ "api_reference" | relative_url }}) |
| equipment_type matching | [Data Model]({{ "data_model" | relative_url }}) — equipment_type section |
| SPARQL prereq, validation | [SPARQL & Validate Prereq]({{ "sparql_validate_prereq" | relative_url }}) |

---

## Config & schema

| Need | Where |
|------|-------|
| Rule YAML schema | [Config Schema]({{ "config_schema" | relative_url }}) |
| Machine-readable schema | docs/config_schema.json |
| Equipment types, rule structure | [Configuration]({{ "configuration" | relative_url }}) |

---

## Data & I/O

| Need | Where |
|------|-------|
| DataFrame input/output contract | [DataFrame Contract]({{ "dataframe-contract" | relative_url }}) |
| Input columns, output flag naming | [DataFrame Contract]({{ "dataframe-contract" | relative_url }}) |
| I/O examples | [DataFrame Contract]({{ "dataframe-contract" | relative_url }}) — I/O examples section |

---

## API & code

| Need | Where |
|------|-------|
| RuleRunner, load_rule, run() | [API Reference]({{ "api_reference" | relative_url }}) |
| Reports (summarize_fault, print_summary, etc.) | [API Reference]({{ "api_reference" | relative_url }}) |
| Full public API | [API Reference]({{ "api_reference" | relative_url }}) |
| Source code, docstrings | open_fdd/ |

---

## Fault definitions & rules

| Need | Where |
|------|-------|
| Built-in rule YAML files | open_fdd/rules/ |
| Example/custom rules | examples/my_rules/ |
| Fault logic (expression, bounds, etc.) | open_fdd/engine/checks.py (internal) |

---

## Workflows & examples

| Need | Where |
|------|-------|
| Brick workflow (TTL → run) | examples/run_all_rules_brick.py |
| Pre-run validation | examples/validate_data_model.py |
| Fault visualization | examples/brick_fault_viz/run_and_viz_faults.ipynb |
| Getting started | [Getting Started]({{ "getting_started" | relative_url }}) |

---

## Agent-specific

| Need | Where |
|------|-------|
| Agent contract | AGENTS.md (repo root) |
| Agent overview | [AI Agents Guide]({{ "ai_agents" | relative_url }}) |
| LLM entrypoint | llms.txt (repo root) |
