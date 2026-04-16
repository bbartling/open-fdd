---
title: Examples
nav_order: 12
nav_exclude: true
---

# Examples

Runnable material under **`examples/`** for the **`open-fdd`** engine on **pandas**.

---

## Column map workshop (Brick, Haystack, DBO, 223P)

One rule file and **`simple_ontology_demo.py`** run the same YAML five times with different **`column_map`** keys — see **`examples/column_map_resolver_workshop/README.md`**.

```bash
pip install open-fdd
python examples/column_map_resolver_workshop/simple_ontology_demo.py
```

---

## AHU notebooks and CSVs

- **`examples/AHU/RTU11_standardized_refactored.ipynb`**, **`examples/AHU/RTU7_standardized_refactored.ipynb`** — open in Jupyter; use bundled CSVs and **`examples/AHU/rules/*.yaml`**.

---

## 223P / full graph workflows

Engine rules stay **ontology-agnostic** via **`column_map`**. **SPARQL, TTL import/export, and hosted graph pipelines** are documented in **[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**.

---

## Cloud export script

If **`examples/cloud_export.py`** exists in your checkout, it is a **sample HTTP client** for a deployed API (not part of the PyPI wheel). Point **`API_BASE`** at your **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** deployment if you use that stack.

---

## More

See **`examples/README.md`** in the repository root.
