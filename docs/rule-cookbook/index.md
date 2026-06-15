---
title: Rule Cookbook
nav_order: 4
---

# Rule Cookbook

Practical patterns for **Arrow-native Rule Lab** on feather historian PyArrow tables — **no pandas on the IoT edge**.

| Page | Use when |
|------|----------|
| [Rule Lab quick start]({{ "/operator-bridge/rule-lab/" | relative_url }}) | Test a rule against live/recent site data in the dashboard |
| [PyArrow rule recipes]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}) | Full Python + Arrow logic, rolling windows, helpers, ML-ready features |
| [DataFusion SQL recipes]({{ "/rule-cookbook/datafusion-sql-recipes/" | relative_url }}) | Simple threshold, CASE WHEN, SQL-readable rules (optional `open-fdd[datafusion]`) |
| [Fault confirmation]({{ "/rule-cookbook/fault-confirmation/" | relative_url }}) | Condition must stay true for N rows or N minutes |
| [Windowing & debugging]({{ "/rule-cookbook/windowing-debugging/" | relative_url }}) | Lookback windows, chunked runs, batch runtime, Rule Lab console |
| [Expression cookbook]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}) | Sensor profile reference (Arrow-native) |
| [GL36 algorithm stubs]({{ "/rule-cookbook/gl36-algorithm-stubs/" | relative_url }}) | Advanced supervisory patterns (doc-only where not executable) |

**PyArrow** is the primary path for complex HVAC FDD and ML prep. **DataFusion SQL** is optional, Rust-ready, and best for simple expression-style rules.

Programmatic sensor defaults: `open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`.

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "zone_temp", cfg, min_true_rows=5)
```
