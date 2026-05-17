---
title: Fault rules for HVAC
nav_order: 8
has_children: true
---

# Fault rules for HVAC

YAML fault rules for HVAC and building systems, evaluated by **`open_fdd.engine.RuleRunner`** on pandas.

Rules reference **logical input names** in YAML. You connect them to DataFrame columns with **`column_map`**. Optional **`brick:`**, **`haystack:`**, **`dbo:`**, or **`223p:`** fields on inputs are supported but **not required** — see [Column map resolvers](../column_map_resolvers).

| Page | Description |
|------|-------------|
| [Overview](overview) | Rule types, `RuleRunner`, column maps |
| [Expression rule cookbook](../expression_rule_cookbook) | Expression recipes (primary reference) |
| [Test bench rule catalog](test_bench_rule_catalog) | Example YAML under `open_fdd/tests/fixtures/rules/` and `examples/AHU/rules/` |
