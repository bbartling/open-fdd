---
title: Home
nav_order: 1
description: "Open-FDD rules engine: fault detection on pandas DataFrames from YAML rules. Published as open-fdd on PyPI."
---

# Open-FDD

The **`open-fdd`** package (**`open_fdd/`** in this repository) is a **rules engine** for building science and HVAC workflows: you define fault checks in **YAML**, map columns on a **pandas** `DataFrame`, and run them with **`RuleRunner`**. It is published to **[PyPI](https://pypi.org/project/open-fdd/)** as a small, dependency-conscious wheel (pandas, NumPy, PyYAML, pydantic).

**Full platform** (data model, APIs, Docker, Brick/223P tooling beyond `column_map`): **[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)** — it uses this library under the hood.

---

## What it does

- **Loads** rule definitions from YAML (bounds, flatline, hunting, expressions, schedules, weather gates, …).
- **Maps** **Brick**, **Haystack**, **DBO**, **223P**, or vendor names to DataFrame columns via **`column_map`** (dict, manifest, or composite resolvers) — same YAML can target different ontologies by swapping the map.
- **Runs** checks over time-indexed or ordered data and returns structured **fault results** (see **`open_fdd.schema`**).

Bring your own data: CSV exports, historian extracts, lab benches, or notebooks. The engine does **not** connect to databases or field buses by itself.

---

## Quick start

```bash
pip install open-fdd
```

From a git checkout:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

See **[Getting started](getting_started)** and **`examples/README.md`** in the repository for runnable entrypoints.

---

## Documentation

| Section | Description |
|---------|-------------|
| [Getting started](getting_started) | Install, tests, examples |
| [Rules overview](rules/overview) | Rule types and YAML structure |
| [Expression rule cookbook](expression_rule_cookbook) | Expressions, ontology labels, schedule & weather gates |
| [Column map resolvers](column_map_resolvers) | Brick / Haystack / DBO / 223P → columns |
| [Engine API](api/engine) | `RuleRunner`, loaders, resolvers |
| [Data modeling & platform (pointer)](modeling/index) | Full stack docs live in **open-fdd-afdd-stack** |
| [How-to guides](howto/index) | PyPI releases, verification, operations |
| [Appendix](appendix/index) | Technical reference, developer guide |

---

## License

MIT — see the repository **`LICENSE`** file.
