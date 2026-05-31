---
name: rules-crud-and-batch-run
description: "Manages saved Python FDD rules from Rule Lab and runs batched jobs against feather timeseries. Use when operators save rules via API or dashboard and execute FDD on stored metrics."
---

# Rules CRUD and batch run

## When to use / When not to use

Use when operators author Python rules in Rule Lab, persist them, and run scheduled or on-demand batch FDD.

For one-shot notebooks with the **library** YAML `RuleRunner`, use [engine-pandas-fdd](../engine-pandas-fdd/SKILL.md) instead (not the operator bridge).

## Prerequisites

- [feather-local-storage](../feather-local-storage/SKILL.md)
- Bridge playground sandbox (`openfdd_bridge.playground`)

## Quick start

| Endpoint | Purpose |
|----------|---------|
| `GET /api/rules/saved` | List saved rules (`rules_store.json`) |
| `POST /api/rules/save` | Create/update rule metadata + inline code |
| `GET/PUT /api/rules/saved/{id}/source` | Read/write `.py` on disk under `data/rules_py/` |
| `POST /api/rules/batch` | Run all enabled rules against modeled sites |
| `POST /api/playground/test-rule` | Preview per-row `evaluate()` on a frame |
| `POST /api/playground/run-script` | Preview DataFrame script mode |

Scheduled loop: `python -m openfdd_bridge.fdd_runner --once` (systemd: `openfdd-fdd-loop`).

## Verification

```bash
pytest tests/workspace_bridge/test_rules_and_fdd.py -q
```

## Gotchas

- Rules execute **server-side** only; browser sends source text to the bridge.
- Set `fault_code` from `GET /api/faults/catalog` when saving — codes are fixed.
- Batch runs can be CPU-heavy; cap `limit` per operator policy.

See [references/REFERENCE.md](references/REFERENCE.md).
