---
title: Verification
parent: How-to Guides
nav_order: 18
---

# Verification

Practical checks when authoring or shipping **`open-fdd`** rules.

---

## 1. Unit tests (CI)

From the repo root with dev dependencies (includes **`[engine]`** libraries):

```bash
pip install -e ".[dev]"
pytest open_fdd/tests/engine
```

Expression cookbook regressions live in **`open_fdd/tests/engine/test_expression_cookbook.py`**.

---

## 2. Rule YAML sanity

- Load each file with **`load_rule()`** or point **`RuleRunner(rules_path=...)`** at the directory.
- Confirm every **`inputs`** key has a matching entry in **`column_map`** (or manifest) before calling **`run()`**.

---

## 3. Small DataFrame smoke test

```python
from pathlib import Path
import pandas as pd
from open_fdd.engine.runner import RuleRunner

df = pd.read_csv("your_sample.csv", parse_dates=["timestamp"]).set_index("timestamp")
runner = RuleRunner(rules_path=Path("path/to/rules"))
out = runner.run(df, timestamp_col="timestamp", column_map={"Supply_Air_Temperature_Sensor": "SAT"})
assert any(c.endswith("_flag") for c in out.columns)
```
