---
title: Modular Architecture
nav_order: 4
---

# Modular architecture

The **`open_fdd`** package is a small library: **rules on pandas**, optional **reporting**.

---

## Modules

| Module | Role |
|--------|------|
| **`open_fdd.engine`** | YAML rules, checks, **`RuleRunner`**, **`column_map`** resolvers |
| **`open_fdd.reports`** | Episode summaries, matplotlib plots, optional Word export |
| **`open_fdd.schema`** | pydantic fault result/event models (engine dependency) |

---

## Engine layers

| Layer | Role |
|-------|------|
| **Rule YAML** | Human-authored definitions loaded by **`load_rule`** / **`RuleRunner`**. |
| **Column map** | Logical names → DataFrame columns (dict, manifest, composite resolver). |
| **Checks** | Bounds, flatline, expression eval, schedule/weather masks, … |
| **Runner** | Orchestrates checks and writes **`*_flag`** columns. |

---

## Reports (optional)

After **`RuleRunner.run`**, use **`open_fdd.reports`** for:

- **`summarize_fault`** / **`summarize_all_faults`** — duration and sensor stats during faults
- **`get_fault_events`** / **`plot_fault_analytics`** — events and charts (`[reports]` extra → matplotlib)
- **`build_report`** — `.docx` when **`python-docx`** is installed

---

## See also

- [Engine API](api/engine)
- [Reports API](api/reports)
- [Expression rule cookbook](expression_rule_cookbook)
- [Column map resolvers](column_map_resolvers)
