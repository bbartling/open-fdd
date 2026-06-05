---
title: Rule Lab
parent: Operator Bridge
nav_order: 3
---

# Rule Lab

Rule Lab is the in-browser editor for Python FDD rules.

## Contract

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    """Return False, True, or (True, window_rows) for retroactive paint."""
```

## Storage

| Artifact | Path |
|----------|------|
| Rule source | `workspace/data/rules_py/<id>.py` |
| Metadata | `workspace/data/rules_store.json` |
| Bindings | Model `fdd_input` + `POST /api/rules/bind` |

Saving in the UI or via API writes both metadata and `.py` file.

## Workflow

1. **Lint** — `POST /api/playground/lint`
2. **Test** — `POST /api/playground/test-rule` on a building time window
3. **Bind** — attach rule to a point in the model
4. **Promote** — enable rule and run batch FDD

Recipes and patterns: [Rule Cookbook](../rule-cookbook/). Tag rules with fault codes from [Fault Codes](../fault-codes/).
