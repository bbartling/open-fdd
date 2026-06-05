---
title: YAML recipes
parent: Rule Cookbook
nav_order: 2
---

# YAML recipes

For **offline** pandas workflows with `open_fdd.engine.RuleRunner` (no Operator Bridge).

```bash
pip install "open-fdd[engine]"
```

## Minimal rule file

```yaml
id: zone_high_temp
type: threshold
column: zone_temp
params:
  upper: 80
  lower: 65
```

```python
from open_fdd.engine import RuleRunner
import pandas as pd

df = pd.read_csv("telemetry.csv")
runner = RuleRunner.from_yaml("rules/zone_high_temp.yaml")
flags = runner.run(df)
```

## When to use YAML vs Python Rule Lab

| YAML engine | Python Rule Lab |
|-------------|-----------------|
| CSV/backfill notebooks | Live edge + dashboard |
| Fixed rule types in engine | Arbitrary `evaluate()` logic |
| CI on historical extracts | BACnet-bound production rules |

Rule type reference and column maps: [Appendix — Python package](../appendix/python-package).
