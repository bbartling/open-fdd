---
title: Expression rule cookbooks
nav_order: 50
has_children: true
---

# Expression rule cookbooks

Open-FDD uses **two rule surfaces**:

| Cookbook | Runtime | Use when |
|----------|---------|----------|
| **[Python / Rule Lab](expression_rule_cookbook_python)** | Edge bridge, feather rows, `evaluate(row, cfg, …)` | **Production** operator stack, Acme, bensserver |
| **[YAML / pandas](expression_rule_cookbook_yaml)** | `open_fdd.engine.RuleRunner` on DataFrames | PyPI, CSV export, notebooks, CI fixtures |

Pick one path per deployment. Edge **scheduled FDD** runs `workspace/data/rules_py/*.py`, not hot-reloaded YAML.

---

## Quick links

- [Rule Lab storage](howto/rule_lab_storage)
- [Rules overview (engine)](rules/overview)
- [Test bench catalog](rules/test_bench_rule_catalog)
