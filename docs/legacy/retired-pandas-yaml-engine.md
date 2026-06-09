---
title: Retired pandas/YAML engine
parent: Developer Guide
nav_exclude: true
---

# Retired: pandas RuleRunner and YAML expression rules

Open-FDD **3.x** edge FDD does **not** use:

- `pandas` DataFrames on the BACnet poll / Docker edge path
- `type: expression` YAML rule files
- `RuleRunner.run(df, column_map=…)` from `open_fdd.engine`

## Use instead

| Legacy | Modern (3.x) |
|--------|----------------|
| YAML `expression:` strings | `apply_faults_arrow()` in `workspace/data/rules_py/` |
| `np.maximum`, `.rolling()` on Series | `pyarrow.compute`, `open_fdd.arrow_runtime.windows` |
| `params` in YAML | Module constants + Rule Lab `cfg` + building-agent tuning |
| `flag: rule_a_flag` | `fault_code` metadata → [Fault codes](../fault-codes/) |

**Cookbook:** [Rule cookbook](../rule-cookbook/) — start at [Expression cookbook (Arrow-native)](../rule-cookbook/expression-cookbook).

**Package:** PyPI `open-fdd` ships `arrow_runtime` + `playground` only. Portfolio Dash may use pandas for CSV analytics.
