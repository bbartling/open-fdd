---
name: engine-pandas-fdd
description: "Runs Open-FDD YAML fault rules on pandas DataFrames via open_fdd.engine. Use when building scripts, notebooks, batch jobs, or services that evaluate FDD rules without a dashboard."
---

# Engine pandas FDD

## When to use / When not to use

Use for **rules-only** workflows: load YAML, map columns, run `RuleRunner`, read `*_flag` columns.

Do not use when the operator only needs a UI or HTTP bridge — compose [fastapi-bridge-api](../fastapi-bridge-api/SKILL.md) or [react-operator-dashboard](../react-operator-dashboard/SKILL.md) instead.

## Prerequisites

- `pip install open-fdd` or editable install from the repo root.
- Python 3.10+.
- Wide pandas DataFrame with timestamp and metric columns.

## Quick start

```python
from pathlib import Path
import pandas as pd
from open_fdd.engine import RuleRunner, load_rule

df = pd.read_csv("site.csv", parse_dates=["timestamp"])
runner = RuleRunner(rules_path=Path("rules"))
column_map = {"SAT": "supply_air_temp", "RAT": "return_air_temp"}
out = runner.run(df, column_map=column_map)
print(out.filter(like="_flag").sum())
```

Rule authoring: [docs/expression_rule_cookbook.md](../../docs/expression_rule_cookbook.md).

## Core concepts

- Rules are YAML files; `load_rule()` returns a dict; `RuleRunner` batches evaluation.
- `column_map` maps ontology/rule input keys to DataFrame column names.
- Results add boolean flag columns and optional detail columns per check type.
- Public API: `RuleRunner`, `load_rule`, `bounds_map_from_rule`, column-map resolvers (see [column-map-and-manifests](../column-map-and-manifests/SKILL.md)).

## Common patterns

- **Single rule probe:** `load_rule(path)` then run one check via runner internals or full `run()`.
- **Examples tree:** copy patterns from `examples/` and `open_fdd/tests/fixtures/rules/`.
- **No platform DB:** engine is in-memory on DataFrames; persistence is operator-owned.

## Compose with other skills

- [column-map-and-manifests](../column-map-and-manifests/SKILL.md) for manifest-driven maps.
- [rules-crud-and-batch-run](../rules-crud-and-batch-run/SKILL.md) when rules live on disk behind an API.
- [feather-local-storage](../feather-local-storage/SKILL.md) when timeseries are stored locally before rule runs.

## Verification

```bash
pip install -e ".[dev]"
pytest open_fdd/tests/engine -q
python -c "from open_fdd.engine import RuleRunner; print(RuleRunner)"
```

## Gotchas

- Expression rules trust YAML authors; validate inputs and units (see cookbook danger zone).
- Column-map misses skip checks silently unless strict validation is enabled in rule params.
- Use `open_fdd.engine`, not a custom runner, in generated code.

See [references/REFERENCE.md](references/REFERENCE.md) for module map and exports.
