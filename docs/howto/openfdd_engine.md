---
title: The optional openfdd-engine package (deprecated)
parent: How-to Guides
nav_order: 22
nav_exclude: true
---

# The optional `openfdd-engine` package (`openfdd_engine`) — deprecated

> **Use `pip install open-fdd` only.** PyPI publishing is **`open-fdd-v*`** via [PyPI releases](openfdd_engine_pypi.md). The **`openfdd-engine`** PyPI workflow was removed; **`packages/openfdd-engine/`** is a legacy editable shim only.

Open-FDD has **one rules implementation**: YAML on **pandas** via **`RuleRunner`** in **`open_fdd.engine`**, plus **`open_fdd.playground`** in the same wheel. The **`openfdd_engine`** import name was a thin re-export for old procurement wording.

---

## Re-exports only

**`openfdd_engine` does not duplicate engine logic.** Its **`__init__.py`** imports from **`open_fdd.engine`** and lists them in **`__all__`**. New public APIs belong in **`open_fdd.engine`** first; the shim gains them through re-export.

- **Versioning:** **`open-fdd`** on PyPI is authoritative; **`openfdd-engine`** pins **`open-fdd>=…`** when published.

---

## Mental model

| Layer | What it is | Typical import |
|-------|------------|----------------|
| **Core engine** | Loads YAML rules, runs checks on a `DataFrame` | `from open_fdd.engine.runner import RuleRunner` |
| **Optional shim** | Same classes, different package name | `from openfdd_engine import RuleRunner` |

---

## When to use `pip install open-fdd` vs `openfdd-engine`

**Default:**

```bash
pip install open-fdd
```

```python
from open_fdd.engine.runner import RuleRunner, load_rule, load_rules_from_dir
from open_fdd.engine.column_map_resolver import load_column_map_manifest
```

**Optional `openfdd-engine`** — only if you need the separate PyPI project or editable shim:

```bash
cd packages/openfdd-engine
pip install -e .
```

See [PyPI releases (`open-fdd`)](openfdd_engine_pypi).

---

## Summary

| Goal | Install | Import |
|------|---------|--------|
| Normal use | `pip install open-fdd` | `open_fdd.engine.*` |
| Optional second package | published `openfdd-engine` or editable shim | `openfdd_engine.*` |

---

## See also

- [Engine-only deployment and external IoT pipelines](engine_only_iot)
- [Modular architecture](../modular_architecture)
- [Expression rule cookbook](../expression_rule_cookbook)
- `packages/openfdd-engine/README.md`
