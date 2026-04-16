---
title: The optional openfdd-engine package
parent: How-to guides
nav_order: 22
---

# The optional `openfdd-engine` package (`openfdd_engine`)

Open-FDD has **one rules implementation**: YAML files evaluated on **pandas** via **`RuleRunner`** in **`open_fdd.engine`**. The **`packages/openfdd-engine/`** tree (PyPI name **`openfdd-engine`**, import **`openfdd_engine`**) is a **thin re-export** of selected symbols from **`open_fdd.engine`** — useful when procurement or legacy imports expect the **`openfdd_engine`** package name.

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
