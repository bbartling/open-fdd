---
title: Expression Rule Cookbook (retired)
nav_exclude: true
redirect_from:
  - /expression_rule_cookbook/
---

# Retired — use Arrow-native cookbook

The pandas **`RuleRunner`** + YAML **`type: expression`** cookbook was removed in **Open-FDD 3.x**.

**Current documentation:** [Expression cookbook (Arrow-native)](rule-cookbook/expression-cookbook)

Edge rules are Python modules with:

```python
def apply_faults_arrow(table, cfg, context=None):
    ...
```

Helpers: `open_fdd.arrow_runtime.cookbook`, `open_fdd.arrow_runtime.primitives`, `open_fdd.arrow_runtime.sensor_catalog`.

Legacy `open_fdd.engine` (pandas) is **not** published on PyPI for 3.x.
