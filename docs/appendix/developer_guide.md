---
title: Developer guide
parent: Appendix
nav_order: 2
description: "open-fdd engine: exported symbols, package layout, tests, and how to extend the library."
---

# Developer guide

The **`open-fdd`** package is the **rules engine**: YAML rule configs, **`RuleRunner`** on **pandas** `DataFrame`s, and helpers to build **`column_map`** from Brick TTL or manifests. Everything on this page is **library scope** only.

---

## Exported symbols

**Typical imports**

```python
from open_fdd import RuleRunner, resolve_from_ttl
```

**Full engine surface** (`open_fdd.engine` — same package, explicit submodule):

| Symbol | Role |
|--------|------|
| `RuleRunner` | Load rules from a directory or list of dicts; `run(df, ...)` adds fault flag columns |
| `load_rule`, `bounds_map_from_rule` | Load one YAML file; extract bounds map for analytics |
| `resolve_from_ttl` | Brick TTL → column mapping (requires **`open-fdd[brick]`**) |
| `BrickTtlColumnMapResolver`, `ManifestColumnMapResolver`, `FirstWinsCompositeResolver`, `load_column_map_manifest` | Build `column_map` for `RuleRunner.run` |

Source: [`open_fdd/engine/`](https://github.com/bbartling/open-fdd/tree/master/open_fdd/engine) on GitHub. Behavior and parameters are documented in **docstrings** on `RuleRunner.run` and resolver classes.

---

## Repository layout

| Path | Role |
|------|------|
| `open_fdd/engine/` | Runner, checks, expression evaluation, column-map resolvers, Brick helpers |
| `open_fdd/schema/`, `open_fdd/reports/` | Shared models and reporting helpers |
| `open_fdd/tests/` | Pytest suites |
| `examples/` | Notebooks and resolver workshops |

---

## Setup and tests

```bash
pip install -e ".[dev]"
pytest open_fdd/tests/ -v --tb=short
```

[TESTING.md](https://github.com/bbartling/open-fdd/blob/master/TESTING.md)

---

## Extending the engine

- New rule **types** or runner behavior → `open_fdd/engine/`; keep on-disk YAML shape stable when possible.
- New **public** symbols → export from [`open_fdd/engine/__init__.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/engine/__init__.py) (and top-level [`open_fdd/__init__.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/__init__.py) when appropriate), then document on this site.

---

## Other repository

The **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** repo documents a separate on-prem **product** that **consumes** this engine (installed from PyPI). For that product, see its **[documentation site](https://bbartling.github.io/open-fdd-afdd-stack/)** — it is not covered here.
