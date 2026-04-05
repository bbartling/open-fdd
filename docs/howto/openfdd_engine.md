---
title: The optional openfdd-engine package
parent: How-to Guides
nav_order: 22
---

# The optional `openfdd-engine` package (`openfdd_engine`)

Open-FDD has **one real rules implementation**: YAML files evaluated on **pandas** via **`RuleRunner`** in the **`open_fdd.engine`** package. Everything else is either that same code in a different wrapper, or documentation about how to deploy it.

This page explains how the **in-repo** package **`packages/openfdd-engine/`** (PyPI name **`openfdd-engine`**, import **`openfdd_engine`**) fits next to **`open_fdd.engine`** and the **Docker `fdd-loop`** service.

---

## Re-exports only — no duplicated types

**`openfdd_engine` does not define its own rule engine, Pydantic models, or resolver types.** The shim **`__init__.py`** imports from **`open_fdd.engine`** (e.g. **`RuleRunner`**, **`resolve_from_ttl`**, **`BrickTtlColumnMapResolver`**, **`ColumnMapResolver`**) and lists them in **`__all__`**. Any new public API should be added **once** under **`open_fdd.engine`**; the shim only gains new names via **import + re-export**.

- **Why:** One source of truth for PyPI **`open-fdd`** and optional **`openfdd-engine`**; no drift between packages.
- **Versioning:** **`open-fdd`** on PyPI is authoritative; **`openfdd-engine`** pins **`open-fdd>=…`** in its **`pyproject.toml`** when published.

The same policy applies to the repo-root **`openfdd_engine/`** namespace used in some dev installs.

---

## Mental model (three layers)

| Layer | What it is | Typical import / entrypoint |
|--------|------------|------------------------------|
| **Core engine** | Loads YAML rules, runs checks on a `DataFrame`, produces fault columns | `from open_fdd.engine.runner import RuleRunner` |
| **Optional shim** | Same classes, different package name (depends on **`open-fdd`**) | `from openfdd_engine import RuleRunner` |
| **Platform loop** | Pulls Timescale data + TTL, builds frames per site, calls **`RuleRunner`**, writes **`fault_results`** | Docker: `python -m openfdd_stack.platform.drivers.run_rule_loop --loop` → `openfdd_stack.platform.loop.run_fdd_loop` |

There is **no second rule engine** inside `openfdd_engine`: its modules **re-export** symbols from **`open_fdd.engine`** (see `packages/openfdd-engine/src/openfdd_engine/runner.py`).

---

## When to use `pip install open-fdd` vs `openfdd-engine`

**Default for everyone (PyPI, notebooks, CI, integrators):**

```bash
pip install open-fdd
```

```python
from open_fdd.engine.runner import RuleRunner, load_rule, load_rules_from_dir
# brick resolution in-platform / with extras:
from open_fdd.engine.brick_resolver import ...
```

**Optional `openfdd-engine` distribution** — use only if you **intentionally** want:

- A **separate PyPI project name** (`openfdd-engine`) for procurement or a minimal dependency line that still pulls **`open-fdd`** underneath, or  
- An **editable install** of only the shim while developing the monorepo:

```bash
cd packages/openfdd-engine
pip install -e .
# optional TTL helpers:
pip install -e ".[brick]"
```

```python
from openfdd_engine import (
    RuleRunner,
    load_rule,
    bounds_map_from_rule,
    resolve_from_ttl,
    BrickTtlColumnMapResolver,
    ColumnMapResolver,
)
```

**Public story:** **`pip install open-fdd`** is the supported install; **`openfdd-engine`** may or may not be published to PyPI as a second project (maintainer setup). See [PyPI releases (`open-fdd`)](openfdd_engine_pypi).

---

## How the full stack uses the engine (so IoT-only users know what they are skipping)

In Docker, **`fdd-loop`** runs:

`python -m openfdd_stack.platform.drivers.run_rule_loop --loop`

That driver:

1. Optionally refreshes Open-Meteo for the lookback window.  
2. Calls **`run_fdd_loop()`** in **`openfdd_stack.platform.loop`**, which loads YAML from **`rules_dir`**, loads timeseries from Postgres, builds **`column_map`** via **`BrickTtlColumnMapResolver`** (Brick TTL — same as historical behavior) from **`config/data_model.ttl`**, and constructs **`RuleRunner`** from **`open_fdd.engine.runner`**. Advanced use: pass **`column_map_resolver=...`** into **`run_fdd_loop`** to swap mapping logic; the default stack does not. Library helpers in **`open_fdd.engine.column_map_resolver`**: **`ManifestColumnMapResolver`**, **`FirstWinsCompositeResolver`**, **`load_column_map_manifest`** (also re-exported from **`openfdd_engine`**).  
3. Writes results to **`fault_results`** (and run log for Grafana).

So: **same YAML and same `RuleRunner` semantics** as a standalone script; the platform adds **DB, schedule, TTL, and weather**.

Operational triggers (touch file, one-shot exec): [Operations — FDD loop](operations#option-a-trigger-the-running-loop-recommended-when-fdd-loop-is-in-docker).

---

## Library-only / external data (no Docker engine mode)

If your data is already in a warehouse or a CSV pipeline, you do **not** need `openfdd_engine` — use **`open_fdd.engine`** on a **`DataFrame`** and the same rule files as the platform. Step-by-step and **`column_map`**: [Engine-only deployment and external IoT pipelines](engine_only_iot).

Worked example under the repo: `examples/engine_iot_playground/`.

---

## Summary

| Goal | Install | Import / run |
|------|---------|----------------|
| Normal development & PyPI users | `pip install open-fdd` | `open_fdd.engine.*` |
| Optional second package name | `pip install -e packages/openfdd-engine` (or published `openfdd-engine`) | `openfdd_engine.*` |
| Scheduled FDD against platform DB | Docker **`--mode engine`** / full stack | `fdd-loop` → `run_rule_loop` → `run_fdd_loop` → `RuleRunner` |

---

## See also

- [Engine-only deployment and external IoT pipelines](engine_only_iot) — `--mode engine` vs pandas `RuleRunner`  
- [PyPI releases (`open-fdd`)](openfdd_engine_pypi) — tags, publishing, `openfdd-engine` scope  
- [Modular architecture](../modular_architecture) — which services run in **engine** mode  
- [Expression rule cookbook](../expression_rule_cookbook) — YAML rule types and patterns  
- Package README: `packages/openfdd-engine/README.md`
