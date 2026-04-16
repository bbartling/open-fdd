---
title: Modular Architecture
nav_order: 4
---

# Modular architecture

This document describes how the **`open_fdd`** package is structured at a high level. The goal is a **small core** (rules + checks + column mapping) that you can embed in notebooks, batch jobs, or larger applications.

---

## Layers

| Layer | Role |
|-------|------|
| **Rule YAML** | Human-authored definitions (bounds, flatline, expression, …) loaded by **`load_rule`** / **`RuleRunner`**. |
| **Column map** | Maps logical names to DataFrame columns (`ColumnMapResolver`, manifest YAML, composite resolvers). |
| **Checks** | Pure functions over Series/DataFrames (bounds, rate of change, expressions with safe eval, …). |
| **Runner** | Orchestrates checks, schedules, and optional weather or derived columns. |
| **Schema** | pydantic models for outputs (fault codes, intervals, metadata). |

---

## Extension points

- **Custom resolvers** — implement the column-map resolver protocol for site-specific naming.
- **Expression rules** — use the documented expression language and built-in helpers (see [Expression rule cookbook](expression_rule_cookbook)).
- **Reports** — optional modules under **`open_fdd.reports`** for visualization or document export (may need extra dependencies).

---

## See also

- [Technical reference](appendix/technical_reference)
- [Column map resolvers](column_map_resolvers)
