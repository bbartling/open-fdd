# `open_fdd.playground` on PyPI

Portable **Python expression FDD** — the same `evaluate(row, cfg, prev_row=None, rows=None)` contract as Rule Lab, edge batch runner, and AWS `fdd_lambda`.

## Install

```bash
pip install open-fdd
# YAML engine (unchanged):
pip install "open-fdd[engine]"
```

## Modules

| Module | Use |
|--------|-----|
| `open_fdd.playground.cookbook` | `cfg_threshold`, `temp_unit_symbol`, `window_rows_1h`, `hour_window_ready`, `attach_rolling_avg` |
| `open_fdd.playground.sandbox` | `lint_python`, `compile_evaluate`, `sweep_rule`, `rule_globals` |
| `open_fdd.playground.rows` | `dataframe_to_evaluate_rows`, `readings_to_evaluate_rows` (Dynamo/MQTT parity) |

## Minimal rule (portable everywhere)

```python
from open_fdd.playground.cookbook import cfg_threshold, temp_unit_symbol

def evaluate(row, cfg, prev_row=None, rows=None):
    v = row.get("temp_rolling_avg") or row.get("temp")
    if v is None:
        return False
    high = cfg_threshold(cfg, "bounds_high")
    if v > high:
        print(f"{row['ts']} OOB {v:.1f}{temp_unit_symbol(cfg)}")
        return True
    return False
```

```python
from open_fdd.playground.sandbox import compile_evaluate, sweep_rule

evaluate = compile_evaluate(open("my_rule.py").read())
flags, events = sweep_rule(open("my_rule.py").read(), cfg={"bounds_high": 80}, rows=rows)
```

## Acme building

Production rules under `workspace/data/rules_py/acme_*.py` import from `open_fdd.playground.cookbook` so they compile the same in:

- Edge Operator Bridge (`prepare_fdd_rows` + `sweep_rule`)
- CI (`scripts/validate_acme_rules_pypi.py`)
- PyPI wheel smoke on tag publish

Validate locally:

```bash
PYTHONPATH=. python scripts/validate_acme_rules_pypi.py
pytest open_fdd/tests/playground -q
```

## AWS `fdd_lambda` migration

In `py-bacnet-stacks-playground/.../fdd_lambda/requirements.txt` add `open-fdd` and replace duplicated `playground_core` helpers with:

```python
from open_fdd.playground.cookbook import attach_rolling_avg, cfg_threshold
from open_fdd.playground.sandbox import compile_evaluate, sweep_rule
from open_fdd.playground.rows import readings_to_evaluate_rows
```

Rolling windows: edge/Acme use **1, 5, 15** minutes; legacy lambda used **1, 5, 10** — align `cfg["rolling_avg_minutes"]` per site.

## CI

`.github/workflows/publish-open-fdd.yml` runs playground import smoke + Acme compile sweep before PyPI upload on `open-fdd-v*` tags.
