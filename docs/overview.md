---
title: System Overview
nav_order: 2
---

# System overview

**Open-FDD** (PyPI **`open-fdd`**, import **`open_fdd`**) runs **YAML fault rules** on **pandas** `DataFrame`s.

On a **git checkout**, the same repo adds an **edge operator stack**: BACnet polling, a local **feather** historian, Python **Rule Lab** rules, and **Ansible** deploys to building VMs. See [Getting started — edge architecture](getting_started#edge-architecture-feather-python-fdd-ansible) for the current diagram and maintenance notes.

---

## Package layout

| Module | Purpose |
|--------|---------|
| **`open_fdd.engine`** | **`RuleRunner`**, rule loading, checks, **`column_map`** resolvers |
| **`open_fdd.reports`** | Fault summaries, episode analysis, plots, optional Word export |
| **`open_fdd.schema`** | Canonical fault result/event models (used by the engine) |

Install **`open-fdd[engine]`** for rule execution; add **`open-fdd[reports]`** for matplotlib-based plots.

---

## Data flow

1. **Your pipeline** builds a time-indexed `DataFrame`.
2. **`column_map`** maps rule input names to column names (optional Brick/Haystack keys in YAML are conventions, not required).
3. **`RuleRunner.run`** returns the DataFrame with **`*_flag`** columns.
4. **`open_fdd.reports`** (optional) summarizes episodes and produces charts or `.docx` reports.

There is no bundled database, HTTP service, or message bus.

---

## Related topics

- [Modular architecture](modular_architecture)
- [Expression rule cookbook](expression_rule_cookbook)
- [Engine API](api/engine)
- [Reports API](api/reports)
