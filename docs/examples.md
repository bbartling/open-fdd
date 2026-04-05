---
title: Examples (repository)
nav_order: 4
---

# Examples in the `open-fdd` repository

All paths are under **[github.com/bbartling/open-fdd/tree/master/examples](https://github.com/bbartling/open-fdd/tree/master/examples)**. Clone the repo, `pip install open-fdd` (or `pip install -e .`), then run from the **repo root**.

**Fastest path — Brick, Haystack, DBO, or 223P column naming:**

```bash
python examples/column_map_resolver_workshop/run_ontology_demo.py --list
python examples/column_map_resolver_workshop/run_ontology_demo.py haystack
```

Start here: **[`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md)** on GitHub.

| Area | What it shows |
|------|----------------|
| **`column_map_resolver_workshop/`** | **`run_ontology_demo.py`** (`brick`, `haystack`, `dbo`, `223p`, `minimal`) + manifests and paired rule YAML ([workshop README](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/README.md)) |
| **`AHU/`** | YAML rules under `rules/`, notebooks, sample CSVs ([folder on GitHub](https://github.com/bbartling/open-fdd/tree/master/examples/AHU)) |

**Docker / BACnet / API** examples and `bootstrap.sh` flows live with the platform: **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.

Install only what you need:

```bash
pip install "open-fdd[brick,viz,dev]"   # notebooks + Brick helpers
```
