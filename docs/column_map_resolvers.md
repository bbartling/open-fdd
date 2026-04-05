---
title: Column map & resolvers
nav_order: 3
---

# Column map & resolvers

Rule YAML references **Brick-style logical names** (e.g. `Supply_Air_Temperature_Sensor`). Your `DataFrame` uses **whatever columns you have** (`sat`, `AHU1_SupplyTemp`, …). The bridge is **`column_map`**: `dict[str, str]` from logical key → **actual column name**.

You can build that dict yourself, load it from a manifest file, derive it from Brick TTL, or **compose** several sources.

## 1. Plain dict (most IoT / warehouse flows)

```python
runner.run(
    df,
    column_map={
        "Supply_Air_Temperature_Sensor": "sat",
        "Outside_Air_Temperature_Sensor": "oat",
    },
)
```

No TTL file required if you already know the mapping.

## 2. Brick TTL (`BrickTtlColumnMapResolver`)

If you have a Brick **`.ttl`** model (same idea as the full stack’s `data_model.ttl`), SPARQL resolution matches the historical platform behavior.

```python
from pathlib import Path
from open_fdd.engine.column_map_resolver import BrickTtlColumnMapResolver

cm = BrickTtlColumnMapResolver().build_column_map(ttl_path=Path("model.ttl"))
runner.run(df, column_map=cm)
```

Requires **`pip install "open-fdd[brick]"`** (rdflib).

## 3. Manifest file (`ManifestColumnMapResolver`)

JSON or YAML: flat `logical → column` or a nested `column_map` object.

```python
from pathlib import Path
from open_fdd.engine.column_map_resolver import ManifestColumnMapResolver

r = ManifestColumnMapResolver(Path("my_mapping.yaml"))
runner.run(df, column_map=r.build_column_map(ttl_path=Path(".")))
```

Helpers: **`load_column_map_manifest(path)`** for the raw dict.

## 4. Composite priority (`FirstWinsCompositeResolver`)

Run multiple resolvers in order; **first wins per key** (e.g. Brick TTL for most points, manifest only for gaps or a second ontology).

```python
from open_fdd.engine.column_map_resolver import (
    BrickTtlColumnMapResolver,
    FirstWinsCompositeResolver,
    ManifestColumnMapResolver,
)

composite = FirstWinsCompositeResolver(
    BrickTtlColumnMapResolver(),
    ManifestColumnMapResolver("extras.yaml"),
)
runner.run(df, column_map=composite.build_column_map(ttl_path=Path("model.ttl")))
```

**Security note:** There is **no** config-driven “import a Python class by string” resolver — use composition in code or a small startup script.

## Where this runs in the full stack

The Docker **FDD loop** defaults to **`BrickTtlColumnMapResolver`** against the published Brick graph. Operators and modelers should use **[AFDD stack → Data modeling](https://bbartling.github.io/open-fdd-afdd-stack/modeling/overview)** and **[Configuration](https://bbartling.github.io/open-fdd-afdd-stack/configuration)** for `rules_dir`, import/export, and TTL lifecycle.

## Examples in the repo

- **`examples/column_map_resolver_workshop/`** — one-shot and multi-ontology illustrations ([README](https://github.com/bbartling/open-fdd/tree/master/examples/column_map_resolver_workshop))
- Other **`examples/`** trees — AHU workshops, 223P-style metadata, etc.

## See also

- [Engine-only deployment and external IoT pipelines](howto/engine_only_iot) — longer integration narrative
- [Fault rules overview](rules/overview) — YAML inputs and Brick-only rule `inputs`
- [Expression rule cookbook](expression_rule_cookbook) — recipes (still Brick-oriented keys)
