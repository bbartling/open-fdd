---
title: Python package
parent: Appendix
nav_order: 2
---

# Python package (`open-fdd`)

Install from PyPI:

```bash
pip install open-fdd                  # Arrow runtime + playground (default 3.0+)
pip install "open-fdd[engine]"        # + YAML RuleRunner (pandas)
pip install "open-fdd[legacy]"        # alias for pandas-backed legacy helpers
```

## Modules

| Module | Purpose |
|--------|---------|
| `open_fdd.arrow_runtime` | **Default** — `apply_faults_arrow` on PyArrow Tables |
| `open_fdd.playground` | Arrow templates + legacy `evaluate()` sandbox |
| `open_fdd.engine` | Optional YAML `RuleRunner` on pandas DataFrames |
| `open_fdd.reports` | Optional summary/plot helpers |

## When to use package-only

| Scenario | Use |
|----------|-----|
| Notebook on CSV export | `engine` + YAML rules |
| Cloud lambda (no UI) | `playground.rule_lab` |
| Full building operator stack | **Docker** Operator Bridge |

## Versioning

Publish: git tag `open-fdd-vX.Y.Z` → GitHub Actions **Publish open-fdd**.

```python
import open_fdd
print(open_fdd.__version__)
```

## Offline example

```python
from open_fdd.engine import RuleRunner
import pandas as pd

df = pd.read_csv("ahu_telemetry.csv")
runner = RuleRunner.from_yaml("rules/high_sat.yaml")
result = runner.run(df)
```

API surface: `open_fdd/engine` docstrings and `docs/config_schema.json` for YAML rule shapes.
