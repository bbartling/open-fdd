---
title: Engine-only deployment and external IoT pipelines
parent: How-to Guides
nav_order: 21
---

# Engine-only deployment and external IoT pipelines

Some integrators already operate **data collection** (historians, MQTT, proprietary BAS exports) and **modeling / semantics** (warehouse schemas, optional Brick elsewhere). Open-FDD’s **`--mode engine`** and the **pandas YAML engine** let you add **FDD** without adopting the full stack.

> **Package names:** The rules code lives under **`open_fdd.engine`**. The repo’s optional **`openfdd-engine`** package (**`openfdd_engine`**) is a thin re-export around the same API — not a different engine. See [The optional openfdd-engine package](openfdd_engine) for a comparison table and Docker vs library paths.

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

### Bring your own `column_map` or resolver

Integrators own the bridge from **their** naming (warehouse columns, Haystack refs, another graph) into what **`RuleRunner`** expects:

1. **Plain dict (most common)** — Build `column_map: dict[str, str]` (rule input / Brick-class key → **actual DataFrame column name**) and pass it to **`RuleRunner.run(..., column_map=column_map)`**. No TTL required on your side if you already know the columns.

2. **Brick TTL in library code** — If you have a Brick **`.ttl`** file (or the same shape as Open-FDD’s model), reuse the platform logic:
   ```python
   from pathlib import Path
   from open_fdd.engine.column_map_resolver import BrickTtlColumnMapResolver

   column_map = BrickTtlColumnMapResolver().build_column_map(ttl_path=Path("path/to/model.ttl"))
   ```
   Same behavior as **`resolve_from_ttl`** when the file exists; requires **`open-fdd[brick]`** / rdflib.

3. **Custom `ColumnMapResolver`** — Implement the **`ColumnMapResolver`** protocol (`build_column_map(*, ttl_path: Path) -> dict[str, str]`) with your own lookup (REST, SQL, manifest file, etc.). You may ignore **`ttl_path`** if your source is elsewhere. For **forked** platform code, **`run_fdd_loop(..., column_map_resolver=your_resolver)`** swaps mapping for the DB loop; the **stock Docker `fdd-loop`** does **not** set this — it keeps **`BrickTtlColumnMapResolver`**.

**Priority / policy:** There is no automatic “ontology priority” in the engine — you supply **one** `column_map` per run (or one resolver that returns it). Ambiguity (e.g. multiple Haystack matches) should be resolved **before** calling **`RuleRunner`** with a strict dict.

Types live in **`open_fdd.engine.column_map_resolver`** and are re-exported from **`openfdd_engine`** (shim only). More context: [The optional openfdd-engine package](openfdd_engine), GitHub **#122** (resolver RFC).

### Manifest file + composite priority (workshop / gap-fill)

- **`load_column_map_manifest(path)`** — reads **`.json`** or **`.yaml`** / **`.yml`**. Accepts either a flat `str → str` object or **`column_map:`** nested mapping.
- **`ManifestColumnMapResolver(path)`** — same map via the **`ColumnMapResolver`** protocol; **`build_column_map`** ignores **`ttl_path`** (manifest is the source of truth for that resolver).
- **`FirstWinsCompositeResolver(r1, r2, ...)`** — runs each resolver in order; **the first resolver to define a key wins** (e.g. **`BrickTtlColumnMapResolver()`** then **`ManifestColumnMapResolver("extras.yaml")`** so TTL fills most keys and the manifest only adds missing ones). This is the supported pattern for **ontology-style priority** without unsafe dynamic imports.

**Config-driven resolver class names** (e.g. loading a Python import path from env) are **not** supported on purpose — easy to turn into **import injection**. Compose resolvers in code or a thin startup script.

**Examples:** `examples/column_map_resolver_workshop/` — **`demo_one_shot.py`** (manifest + **`RuleRunner`**), **`demo_multi_ontology_illustration.py`** (illustrative Brick / Haystack / DBO / 223P key shapes).

**Install**

```bash
pip install -e ".[dev]"   # from open-fdd clone, or
pip install open-fdd      # when using a published version that includes the engine
```

The repo also contains an optional **`openfdd-engine`** tree (`packages/openfdd-engine/`) that re-exports the same API; **`pip install open-fdd`** is the supported public install — use **`open_fdd.engine`** after install. More detail: [The optional openfdd-engine package](openfdd_engine).

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
