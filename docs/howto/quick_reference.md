---
title: Quick reference
parent: How-to Guides
nav_order: 0
nav_exclude: true
---

# Quick reference

One-page cheat sheet for the **`open-fdd`** rules engine. Deeper detail: [Verification](verification), [Configuration](../configuration), [Engine API](../api/engine).

---

## What it is

**`open-fdd`** evaluates **YAML** fault rules on **pandas** `DataFrame`s. Install with **`pip install open-fdd`**. There is no bundled database, Docker stack, or HTTP API in this repository.

---

## Common commands

| Goal | Command |
|------|---------|
| Install (dev checkout) | `pip install -e ".[dev]"` |
| Run tests | `pytest` |
| Import check | `python -c "import open_fdd; print('ok')"` |

---

## Minimal Python snippet

```python
from pathlib import Path
from open_fdd.engine.runner import RuleRunner

runner = RuleRunner(rules_path=Path("path/to/rules_dir"))
out = runner.run(df, timestamp_col="timestamp", column_map={"Supply_Air_Temperature_Sensor": "sat"})
```

---

## Docs links

- [Getting started](../getting_started)
- [Engine-only / IoT](engine_only_iot)
- [Column map resolvers](../column_map_resolvers)
