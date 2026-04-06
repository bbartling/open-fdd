---
title: Examples (repository)
nav_order: 4
---

# Examples in the `open-fdd` repository

All paths are under **[github.com/bbartling/open-fdd/tree/master/examples](https://github.com/bbartling/open-fdd/tree/master/examples)**. Clone the repo, `pip install open-fdd` (or `pip install -e .`), then run from the **repo root**.

**Fastest path — one rule, different `column_map` keys (Brick / Haystack / DBO / 223P):**

```bash
python examples/column_map_resolver_workshop/simple_ontology_demo.py
```

Start here: **[`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md)** on GitHub.

| Area | What it shows |
|------|----------------|
| **`column_map_resolver_workshop/`** | **`simple_ontology_demo.py`** + **`simple_ontology_rule.yaml`** ([workshop README](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/README.md)) |
| **`AHU/`** | YAML rules under `rules/`, notebooks, sample CSVs ([folder on GitHub](https://github.com/bbartling/open-fdd/tree/master/examples/AHU)) |

**Docker / BACnet / API** examples and platform setup live in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.

Install only what you need:

```bash
pip install open-fdd matplotlib         # notebooks: add matplotlib for plotting
```
