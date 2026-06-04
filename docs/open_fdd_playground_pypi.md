---
title: PyPI — engine, reports, and playground
nav_order: 59
description: "pip install open-fdd: YAML RuleRunner, portable evaluate() sandbox, and optional reports. Edge operator UI is separate."
---

# PyPI packages (`open-fdd`)

The **front-runner product** is the **operator web app** in this repo: Docker bridge + React dashboard, BACnet, Rule Lab, feather historian, and check-engine on the edge. That stack is **not** installed from PyPI.

**PyPI** ships library wheels for notebooks, CI, AWS lambda, and offline CSV work:

```bash
pip install open-fdd
pip install "open-fdd[engine]"   # YAML RuleRunner (pyyaml, pydantic)
pip install "open-fdd[reports]"  # matplotlib summaries (optional)
```

Current release line: **`open-fdd` 2.4.x** on [pypi.org/project/open-fdd](https://pypi.org/project/open-fdd/). Tag `open-fdd-v*` to publish (see `.github/workflows/publish-open-fdd.yml`).

---

## What is on PyPI

| Module | Role |
|--------|------|
| **`open_fdd.engine`** | YAML fault rules → pandas `*_flag` columns via **`RuleRunner`** |
| **`open_fdd.reports`** | Episode summaries and plots after a run (`[reports]` extra) |
| **`open_fdd.schema`** | Pydantic fault models (engine dependency) |
| **`open_fdd.playground`** | Portable **`evaluate(row, cfg, …)`** sandbox — cookbook helpers, lint/compile/sweep, row builders |

The edge **Operator Bridge** imports `open_fdd.playground` from the same source tree (or from an installed wheel inside the image). Production **Acme** expression rules use:

```python
from open_fdd.playground.cookbook import cfg_threshold, temp_unit_symbol, window_rows_1h
```

---

## `open_fdd.playground` (expression FDD)

Same contract as **Rule Lab** and AWS **`fdd_lambda`**: one function per rule.

| Submodule | Use |
|-----------|-----|
| `open_fdd.playground.cookbook` | `cfg_threshold`, `temp_unit_symbol`, `window_rows_1h`, `hour_window_ready`, `attach_rolling_avg` |
| `open_fdd.playground.sandbox` | `lint_python`, `compile_evaluate`, `sweep_rule`, `rule_globals` |
| `open_fdd.playground.rows` | `dataframe_to_evaluate_rows`, `readings_to_evaluate_rows` |

Minimal rule:

```python
from open_fdd.playground.cookbook import cfg_threshold, temp_unit_symbol

def evaluate(row, cfg, prev_row=None, rows=None):
    v = row.get("temp_rolling_avg") or row.get("temp")
    if v is None:
        return False
    if v > cfg_threshold(cfg, "bounds_high"):
        return True
    return False
```

Run a sweep:

```python
from open_fdd.playground.sandbox import compile_evaluate, sweep_rule

code = open("my_rule.py").read()
flags, events = sweep_rule(code, {"bounds_high": 80}, rows)
```

**Acme** rules under `workspace/data/rules_py/acme_*.py` are validated with:

```bash
PYTHONPATH=. python scripts/validate_acme_rules_pypi.py
pytest open_fdd/tests/playground -q
```

**AWS lambda:** add `open-fdd` to `fdd_lambda/requirements.txt` and replace duplicated `playground_core` helpers with `open_fdd.playground` imports. Rolling windows: edge uses **1 / 5 / 15** minutes; legacy lambda used **1 / 5 / 10** — set `cfg["rolling_avg_minutes"]` per site.

---

## YAML engine (offline pandas)

For historian CSV export without the bridge:

```python
from open_fdd.engine import RuleRunner

runner = RuleRunner.from_yaml_dir("rules/", column_map={"SAT": "supply_air_temp"})
df = runner.run(df)
```

See [Fault rules (engine)](rules/) and [YAML expression cookbook](expression_rule_cookbook_yaml).

---

## Related (operator product, not PyPI)

| Topic | Doc |
|-------|-----|
| Deploy the web app | [Getting started](getting_started), [Docker edge deploy](edge_deploy_docker) |
| Python rules in Rule Lab | [Python expression cookbook](expression_rule_cookbook_python) |
| Bridge REST | [Bridge API](appendix/bridge_api) |
| Post-deploy probes | [Verification](howto/verification) |

---

## Also published

| Package | PyPI |
|---------|------|
| `open-fdd` | [open-fdd](https://pypi.org/project/open-fdd/) |
| `openfdd-engine` | Thin re-export of `open_fdd.engine` (tag `openfdd-engine-v*`) |

Docker images (`openfdd-bridge`, commission, MCP) are built from this repo — see [Publish Docker addons](howto/publish_docker_addons).
