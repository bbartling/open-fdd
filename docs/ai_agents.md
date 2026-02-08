---
title: AI Agents Guide
nav_order: 20
---

# AI Agents Guide

This document provides structured context for AI agents (LLMs, code assistants, automation) working with open-fdd. Use it to understand the project, data flow, and how to extend or integrate it.

---

## What is open-fdd?

**open-fdd** is a config-driven Fault Detection and Diagnostics (FDD) engine for HVAC systems. It runs YAML-defined fault rules against pandas DataFrames and outputs boolean fault flags per rule. It supports optional **BRICK** semantic building models for column resolution.

- **Input:** Time-series DataFrame (sensor data) + YAML rules
- **Output:** Same DataFrame + fault flag columns (boolean)
- **Optional:** Brick TTL model for `column_map` resolution

---

## Core concepts

| Concept | Description |
|---------|-------------|
| **Rule** | YAML file with `name`, `type`, `flag`, `inputs`, optional `params` and `expression` |
| **Rule type** | `bounds`, `flatline`, `expression`, `hunting`, `oa_fraction`, `erv_efficiency` |
| **Flag** | Output column name (e.g. `rule_a_flag`). True = fault at that timestamp |
| **column_map** | Dict mapping BRICK class (or rule input) → DataFrame column name |
| **BRICK** | Semantic building ontology. Rule inputs use BRICK class names as keys for model-driven resolution |

---

## Rule types at a glance

| Type | Built-in? | Purpose |
|------|-----------|---------|
| `expression` | No (custom logic) | Pandas/NumPy expression; True = fault |
| `bounds` | Yes | Value outside [low, high] |
| `flatline` | Yes | Sensor stuck (rolling spread < tolerance) |
| `hunting` | Yes | Excessive AHU state changes |
| `oa_fraction` | Yes | OA fraction vs design minimum |
| `erv_efficiency` | Yes | ERV effectiveness out of range |

---

## BRICK naming convention

- **Rule input keys** = variable names in expressions. Use **BRICK class names** (e.g. `Supply_Air_Temperature_Sensor`) for Brick compatibility.
- **`column`** = fallback DataFrame column when no `column_map`.
- **`brick`** = explicit Brick class when input key differs (e.g. `Heating_Valve_Command` with `brick: Valve_Command`).
- **`column_map`** keys = BRICK class names. For duplicate classes: `Valve_Command|heating_sig`.

---

## Data flow

```
DataFrame (raw BAS columns)
    ↓
column_map (BRICK class → df column)  [optional, from Brick TTL or manual]
    ↓
RuleRunner.run(df, column_map=...)
    ↓
DataFrame + fault flag columns (rule_a_flag, rule_b_flag, ...)
```

---

## Key API surface

```python
from open_fdd import RuleRunner
from open_fdd.reports import summarize_fault, print_summary
from open_fdd.engine import load_rule
from open_fdd.engine.brick_resolver import resolve_from_ttl, get_equipment_types_from_ttl

# Load rules
runner = RuleRunner(rules_path="open_fdd/rules")
# or from list
runner = RuleRunner(rules=[load_rule("ahu_rule_a.yaml")])

# Run
result = runner.run(df, column_map=column_map, rolling_window=3)

# Reports
summary = summarize_fault(result, flag_col="rule_a_flag", timestamp_col="timestamp")
print_summary(summary, "Rule A")
```

---

## Brick workflow

1. **Brick TTL** — Points have `ofdd:mapsToRuleInput` and `rdfs:label` → CSV column.
2. **resolve_from_ttl(ttl_path)** → `column_map` (BRICK class → df column).
3. **get_equipment_types_from_ttl(ttl_path)** → equipment types for rule filtering.
4. **Rule `equipment_type`** — Only rules whose `equipment_type` matches the model run.

---

## Common tasks for AI agents

1. **Add a new expression rule** — Copy a cookbook rule, change inputs to BRICK classes, adjust expression.
2. **Map custom DataFrame to rules** — Build `column_map = {BRICK_class: your_column_name}`.
3. **Run without Brick** — Use `column` in rule inputs; `column_map` can key by rule input name.
4. **Validate before run** — Use `examples/validate_data_model.py` with Brick TTL.

---

## File layout

| Path | Purpose |
|------|---------|
| `open_fdd/rules/` | Built-in rule YAML files |
| `open_fdd/engine/` | RuleRunner, checks, brick_resolver |
| `open_fdd/reports/` | summarize_fault, print_summary |
| `examples/run_all_rules_brick.py` | Brick workflow entrypoint |
| `examples/validate_data_model.py` | Pre-run validation |
| `docs/expression_rule_cookbook.md` | Rule recipes (BRICK-based) |
| **[open-fdd-datalake](https://github.com/bbartling/open-fdd-datalake)** | Separate repo — end-to-end framework (ingest, Brick, FDD, docx) for real BAS data |

---

## Expression rule structure

```yaml
name: rule_name
type: expression
flag: output_flag_name
equipment_type: [AHU, VAV_AHU]  # optional

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Valve_Command:
    brick: Valve_Command
    column: heating_sig

params:
  err_thres: 1.0

expression: |
  (Supply_Air_Temperature_Sensor < 50) & (Valve_Command > 0.9)
```

- **Expression** uses input keys as variables. NumPy available as `np`.
- **Result** must be boolean Series (True = fault).

---

## Related docs

- [Configuration]({{ "configuration" | relative_url }}) — Rule types, YAML structure
- [API Reference]({{ "api_reference" | relative_url }}) — RuleRunner, reports, brick_resolver
- [Data Model & Brick]({{ "data_model" | relative_url }}) — Brick workflow, column map
- [Expression Rule Cookbook]({{ "expression_rule_cookbook" | relative_url }}) — Rule recipes
