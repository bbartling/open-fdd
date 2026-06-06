---
title: Python package
parent: Appendix
nav_order: 2
---

# Python package (`open-fdd`)

Install from PyPI:

```bash
pip install open-fdd                  # Arrow runtime + playground (default 3.0.1+)
pip install "open-fdd[ml]"            # optional numpy/sklearn for offline graph ML experiments
```

## Modules

| Module | Purpose |
|--------|---------|
| `open_fdd.arrow_runtime` | **Default** — `apply_faults_arrow` on PyArrow Tables, cookbook masks, column maps |
| `open_fdd.playground` | Rule Lab lint/compile helpers for Arrow rules |

Retired in 3.0.1+: `open_fdd.engine` (YAML/pandas `RuleRunner`) is **not** shipped on PyPI. Use Operator Bridge Rule Lab or import rules from `workspace/data/rules_py/`.

## When to use package-only

| Scenario | Use |
|----------|-----|
| Lint/test Arrow rules offline | `open_fdd.arrow_runtime` + `open_fdd.playground` |
| Graph ML experiments (Layer B) | `open-fdd[ml]` in `experiments/` (see issue #211) |
| Full building operator stack | **Docker** Operator Bridge |

## Versioning

Publish: git tag `open-fdd-vX.Y.Z` → GitHub Actions **Publish open-fdd**.

```python
import open_fdd
print(open_fdd.__version__)
```

## Offline Arrow example

```python
import pyarrow as pa
import pyarrow.compute as pc
from open_fdd.arrow_runtime import run_arrow_rule

code = '''
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["SAT"], float(cfg["high"]))
'''
table = pa.table({"SAT": [70.0, 90.0, 88.0]})
result = run_arrow_rule(code, table, {"high": 85})
print(result.flagged_count)
```

API surface: `open_fdd/arrow_runtime` docstrings and [Arrow recipes](../rule-cookbook/arrow-recipes).
