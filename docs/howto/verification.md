---
title: Verification
parent: How-to guides
nav_order: 18
---

# Verification

Practical checks when authoring or shipping **`open-fdd`** rules.

---

## 1. Unit tests (CI)

From the repo root with dev dependencies:

```bash
pip install -e ".[dev]"
pytest
```

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
assert out.filter(like="_flag").shape[1] >= 1
```

---

## Platform / database checks

For HTTP APIs, databases, Brick / 223P graph workflows, and observability around a deployed stack, see **[open-fdd-afdd-stack documentation](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**.
