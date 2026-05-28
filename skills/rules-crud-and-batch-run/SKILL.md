---
name: rules-crud-and-batch-run
description: "Manages YAML FDD rule files on disk and runs batched RuleRunner jobs against feather timeseries. Use when operators edit rules via API or dashboard and execute FDD on stored metrics."
---

# Rules CRUD and batch run

## When to use / When not to use

Use when rules live under `<data_dir>/rules` with HTTP CRUD and batch execution.

For one-shot scripts, use [engine-pandas-fdd](../engine-pandas-fdd/SKILL.md) only.

## Prerequisites

- [feather-local-storage](../feather-local-storage/SKILL.md)
- `open_fdd.engine.RuleRunner`

## Quick start

- `GET /rules` — list YAML filenames.
- `GET /rules/{filename}` — fetch content.
- `PUT /rules/{filename}` — replace content.
- `POST /rules/run` — body: site_id, sources, optional rule subset; load frames, run runner, return summary.

## Verification

```bash
pytest open_fdd/tests/desktop/test_rule_loop_batched.py -q
```

## Gotchas

- Validate YAML before save; sync definitions if using defaults catalog.
- Batch runs can be CPU-heavy; cap sites/columns per operator policy.

See [references/REFERENCE.md](references/REFERENCE.md).
