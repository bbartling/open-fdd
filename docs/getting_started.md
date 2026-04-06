---
title: Getting started
nav_order: 2
description: "pip install open-fdd, RuleRunner on a pandas DataFrame, column_map from Brick keys to your columns."
---

# Getting started

You need **Python 3.9+** and **pip**. Basic **pandas** usage is enough to run rules.

## Install

```bash
pip install open-fdd
```

**Included with `pip install open-fdd`:** **pytest** (running tests from a clone). The engine does **not** bundle **rdflib**; Brick **`.ttl`** → `column_map` is implemented in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** (`openfdd_stack.platform.brick_ttl_resolver`).

**Install separately if you need them:** **matplotlib** (notebooks / plotting), **python-docx** (Word export in report helpers), **black** / **pre-commit** (formatting — see repo config).

BACnet, FastAPI, and other **platform** dependencies live in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**, not in this package.

## Run rules on a DataFrame

Rules are YAML (`type`, `inputs`, `params`, `flag`, …). In YAML, **`inputs`** are keyed by **Brick-style names** (e.g. `Outside_Air_Temperature_Sensor`). Your `DataFrame` almost certainly uses **different column names** — pass **`column_map`** so each rule input points at the right column.

```python
import pandas as pd
from open_fdd import RuleRunner

df = pd.DataFrame(
    {
        "timestamp": pd.date_range("2024-01-01", periods=24, freq="h"),
        "oat": [72.0, 74.0, 95.0] + [55.0] * 21,  # one hot stretch
    }
)

runner = RuleRunner(
    rules=[
        {
            "name": "oat_too_hot",
            "type": "expression",
            "flag": "oat_too_hot_flag",
            "inputs": {
                "Outside_Air_Temperature_Sensor": {
                    "brick": "Outside_Air_Temperature_Sensor",
                },
            },
            "params": {"hi": 90.0},
            "expression": "Outside_Air_Temperature_Sensor > hi",
        }
    ]
)

df_out = runner.run(
    df,
    timestamp_col="timestamp",
    column_map={"Outside_Air_Temperature_Sensor": "oat"},
)
# df_out includes oat_too_hot_flag (and original columns)
```

**Load rules from disk** instead of inline dicts:

```python
runner = RuleRunner("/path/to/dir/of/yaml/rules")
df_out = runner.run(df, timestamp_col="timestamp", column_map={...})
```

If a rule references columns you do not have, use **`skip_missing_columns=True`** so those rules are skipped instead of raising. More mapping options: [Column map & resolvers](column_map_resolvers). For CSV → `DataFrame`, use **`pandas.read_csv`** then **`runner.run(df, ...)`**; sample data and notebooks: [Examples](examples).

The **same YAML** runs in the full Docker platform; there the stack builds **`column_map`** from the data model. Here **you** supply the map (dict or **`load_column_map_manifest`** / **`ManifestColumnMapResolver`**).

## Clone and run tests (contributors)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv env && source env/bin/activate
pip install -U pip && pip install -e .
pytest
```

More detail: [TESTING.md](https://github.com/bbartling/open-fdd/blob/master/TESTING.md).

## Full platform operators

Compose services, Caddy, BACnet, REST APIs, and the React UI are documented in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**:

[bbartling.github.io/open-fdd-afdd-stack](https://bbartling.github.io/open-fdd-afdd-stack/)

## PyPI releases (maintainers)

Version bumps, tags, and the companion **`openfdd-engine`** package (same code, alternate install name) are covered in the stack docs:

[PyPI releases (`open-fdd`)](https://bbartling.github.io/open-fdd-afdd-stack/howto/openfdd_engine_pypi)
