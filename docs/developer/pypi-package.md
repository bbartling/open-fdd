---
title: PyPI package
parent: Developer
nav_order: 9
---

# PyPI package (`open-fdd`)

## What it is

Embeddable **Arrow-native FDD compute** for consultants, cloud pipelines, and test benches:

- Lint and test `apply_faults_arrow(table, cfg, context)` rules
- Run rules on PyArrow Tables, Feather, or Parquet
- Optional NumPy analytics helpers (`pip install "open-fdd[analytics]"`)

## What it is not

The PyPI wheel does **not** include:

- Operator Bridge / FastAPI app
- React dashboard
- BACnet commission/poll service
- MCP server
- Ansible / Tailscale deploy tooling

Use **GHCR Docker images** for the full edge stack.

## Install

```bash
pip install open-fdd
pip install "open-fdd[analytics]"   # optional NumPy helpers
pip install "open-fdd[ml]"          # offline sklearn experiments
```

## CLI

```bash
open-fdd version
open-fdd lint-rule path/to/rule.py
open-fdd test-rule path/to/rule.py --input sample.feather --config cfg.json
open-fdd run-arrow path/to/rule.py --input in.feather --output out.feather
open-fdd validate-rule-pack ./rules
```

## Rule contract

```python
def apply_faults_arrow(table, cfg, context=None):
    # return PyArrow bool mask, length == table.num_rows
    ...
```

Use `open_fdd.arrow_runtime.run_arrow_rule` for structured `ArrowRuleResult` (counts, errors, preview).

## Modules shipped on PyPI

| Module | Purpose |
|--------|---------|
| `open_fdd.arrow_runtime` | Rule execution, cookbook masks, column maps |
| `open_fdd.playground` | Lint/compile helpers |
| `open_fdd.faults` | Fault catalog YAML |
| `open_fdd.schema` | Result schemas |

`open_fdd.engine` (pandas/YAML) is **not** in the wheel.

## Examples

Repo `examples/` — [arrow_minimal](https://github.com/bbartling/open-fdd/tree/master/examples/arrow_minimal), Feather batch, generic IoT pipeline.

## Local validation

```bash
pip install -e ".[test,dev,analytics]"
python scripts/release/check_version.py
pytest open_fdd/tests -q
python -m build && twine check dist/*
```
