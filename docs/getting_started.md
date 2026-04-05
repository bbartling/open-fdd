---
title: Getting started
nav_order: 2
---

# Getting started

You need **Python 3.9+** and **pip**. Familiarity with **pandas** is enough to be productive.

## Install

```bash
pip install open-fdd
```

Optional extras (see [`pyproject.toml`](https://github.com/bbartling/open-fdd/blob/master/pyproject.toml) on GitHub):

- **`[brick]`** — Brick TTL → column map (`BrickTtlColumnMapResolver`, SPARQL helpers)
- **`[viz]`**, **`[bacnet]`**, **`[dev]`** — notebooks, tests, tooling

## Minimal usage

```python
from open_fdd import RuleRunner

runner = RuleRunner("/path/to/rules")  # directory of `.yaml` files
df_out = runner.run(df)                 # your DataFrame: traces as columns
```

Rules are the same YAML shape whether you use the library or the full platform. Inputs use **Brick class names**; you supply a **`column_map`** from those names to **your** column names unless you use a [resolver](column_map_resolvers) or Brick TTL.

## Clone and run tests (contributors)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e ".[dev]"
pytest open_fdd/tests/ -v --tb=short
```

More detail: [TESTING.md](https://github.com/bbartling/open-fdd/blob/master/TESTING.md).

## Optional import shim: `openfdd_engine`

There is **one** rule engine (`open_fdd.engine`). The **`openfdd-engine`** PyPI package is an optional **re-export** (`import openfdd_engine`) for legacy layouts; it does not duplicate logic. See the table in [Engine-only / IoT](howto/engine_only_iot#library-path--same-yaml-any-dataframe).

## Full platform operators

Bootstrap, ports, Caddy, data model, BACnet, and REST APIs live in the **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** docs:

[bbartling.github.io/open-fdd-afdd-stack](https://bbartling.github.io/open-fdd-afdd-stack/)

## PyPI releases (maintainers)

Version bumps, tags, and **`openfdd-engine`** alignment are described in the stack docs (shared release checklist):  
[PyPI releases (`open-fdd`)](https://bbartling.github.io/open-fdd-afdd-stack/howto/openfdd_engine_pypi).
