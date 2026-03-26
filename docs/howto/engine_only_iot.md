---
title: Engine-only deployment and external IoT pipelines
parent: How-to Guides
nav_order: 21
---

# Engine-only deployment and external IoT pipelines

Some integrators already operate **data collection** (historians, MQTT, proprietary BAS exports) and **modeling / semantics** (warehouse schemas, optional Brick elsewhere). Open-FDD’s **`--mode engine`** and the **pandas YAML engine** let you add **FDD** without adopting the full stack.

## What `--mode engine` starts (Docker)

From the repo root:

```bash
./scripts/bootstrap.sh --mode engine
```

This brings up **TimescaleDB**, the **`fdd-loop`** service, and **`weather-scraper`** — see [Modular architecture](../modular_architecture.md) for the matrix. There is **no** API, React, or BACnet scraper in this slice by default.

**When it fits**

- You will **load aligned time-series into Postgres** (same DB the platform uses) and let the existing loop consume **rules + data model** from the normal Open-FDD deployment pattern.
- You want **weather-augmented** or **scheduled** FDD in the same containerized runtime as production Open-FDD.

**When something else fits better**

- Your data lives in **Snowflake / BigQuery / a lake** and you only need **rule evaluation** on batches or streams: use the **Python library** path below (no Docker).

## Library path — same YAML, any DataFrame

The rule runner is **`open_fdd.engine.runner.RuleRunner`**. It loads the **same** `.yaml` rule files as the platform (`type: bounds|flatline|expression|hunting|oa_fraction|erv_efficiency`, `inputs`, `params`, etc.). Authoring references:

- [Expression rule cookbook](../expression_rule_cookbook.md)
- Examples under `examples/my_rules/` in the repo

**Minimal integration pattern**

1. Build a **pandas** `DataFrame` whose columns are your sensor traces (and optional `timestamp`).
2. Point **`RuleRunner`** at a directory of `.yaml` files **or** pass `rules=[...]` dicts.
3. Call **`run(df, timestamp_col=..., skip_missing_columns=True, column_map={...})`**.
4. Read boolean **`*_flag`** columns (and optional rolling persistence — same parameters as in-platform).

**`column_map`** — when your modeling layer uses Brick class URIs or tags but dataframe columns are different (e.g. `temp_sa` vs `Supply_Air_Temperature_Sensor`), pass the same **`column_map`** concept the platform uses after SPARQL resolution. See `RuleRunner.run` docstring in `open_fdd/engine/runner.py`.

**Install**

```bash
pip install -e ".[dev]"   # from open-fdd clone, or
pip install open-fdd      # when using a published version that includes the engine
```

The **`openfdd-engine`** PyPI package is a **small re-export** of the same API (`RuleRunner`, `load_rule`, …) for dependents that want an explicit engine package name; it still relies on the **`open-fdd`** distribution for implementation.

## Standalone playground (optional)

An **in-repo** example folder is included for workshops and quick starts:

- `examples/engine_iot_playground/` with `README.md`, `rules/*.yaml`, `data/RTU11.csv`, `run_demo.py`, and `RTU11_engine_tutorial.ipynb`.

That pattern is **not** a second engine — it is the **same** code path as production rules, without Docker.

## Summary

| Approach | You bring | Open-FDD provides |
|----------|-----------|-------------------|
| **`--mode engine`** | Postgres feed + ops for containers | `fdd-loop`, weather worker, DB |
| **`RuleRunner` in Python** | DataFrame + YAML directory | Identical rule YAML semantics on pandas |
| **Full stack** | BACnet / UI needs | Collector + model + engine together |

For mode overview and service list, start at [Modular architecture](../modular_architecture.md).
