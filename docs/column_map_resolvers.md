---
title: Column map & resolvers
nav_order: 3
description: "Map Brick-style rule input names to DataFrame columns: dict, manifest, or composite resolvers; Brick TTL mapping is stack-only."
---

# Column map & resolvers

YAML rules name their **`inputs`** with **logical keys**—often **Brick** class names (e.g. `Supply_Air_Temperature_Sensor`) on the stack, but the same mechanism supports **Haystack-style slugs**, **DBO** type names, or **223P-scoped** identifiers if those strings match your map. Your **`pandas`** frame uses **your** column names (`sat`, `AHU1_SupplyTemp`, …). See [Expression Rule Cookbook — ontology labels](expression_rule_cookbook#ontology-labels).

**`column_map`** is the bridge: `dict[str, str]` where each **key** is a **logical label** (Brick class, or a string from the rule’s optional **`haystack` / `dbo` / `s223` / `223p`** fields on that input), and each **value** is the **actual `DataFrame` column name**. `RuleRunner` tries those fields in order until one matches a map key; see [Expression Rule Cookbook](expression_rule_cookbook#ontology-labels).

Pass it to **`RuleRunner.run(..., column_map=...)`**. You can build that dict by hand, load it from a manifest, or **merge** several sources with a composite resolver. Deriving the map from a Brick **`.ttl`** file is done on the **[AFDD stack](https://github.com/bbartling/open-fdd-afdd-stack)** (rdflib), not in the **`open-fdd`** package.

---

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

No TTL file required if you already know the mapping. Keys must match the **input names** used in your rule YAML (see [Fault rules overview](rules/overview)).

---

## 2. Brick TTL (AFDD stack only)

If you run the **Docker AFDD platform**, **`fdd-loop`** builds **`column_map`** from **`config/data_model.ttl`** using **`BrickTtlColumnMapResolver`** in **`openfdd_stack.platform.brick_ttl_resolver`** (depends on **rdflib** / **pyparsing**, declared in the stack’s **`pyproject.toml`** — not in **`open-fdd`**).

For **engine-only** notebooks and pipelines, use a **manifest** (below) or a **plain dict** that lists the same logical keys your rules use.

---

## 3. Manifest file (`ManifestColumnMapResolver`)

**JSON** or **YAML**: either a flat `logical_name → column_name` object, or a top-level **`column_map:`** nested mapping.

```python
from pathlib import Path
from open_fdd.engine.column_map_resolver import ManifestColumnMapResolver

r = ManifestColumnMapResolver(Path("my_mapping.yaml"))
runner.run(df, column_map=r.build_column_map(ttl_path=Path(".")))
```

For a raw dict without the resolver class, use **`load_column_map_manifest(path)`** from the same module.

---

## 4. Composite priority (`FirstWinsCompositeResolver`)

Run multiple resolvers **in order**; for each logical key, the **first resolver that defines it wins** (for example: a base manifest, then an override file that only adds missing keys). On the stack you can compose the stack’s **`BrickTtlColumnMapResolver`** with a **`ManifestColumnMapResolver`** in your own startup code.

```python
from pathlib import Path
from open_fdd.engine.column_map_resolver import (
    FirstWinsCompositeResolver,
    ManifestColumnMapResolver,
)

composite = FirstWinsCompositeResolver(
    ManifestColumnMapResolver("base.yaml"),
    ManifestColumnMapResolver("extras.yaml"),
)
runner.run(df, column_map=composite.build_column_map(ttl_path=Path(".")))
```

**Security:** There is **no** env-driven “import a resolver class by string” — compose resolvers in code or a small startup script.

---

## Examples in the repo

Minimal workshop — **`examples/column_map_resolver_workshop/`** ([folder on GitHub](https://github.com/bbartling/open-fdd/tree/master/examples/column_map_resolver_workshop)):

| Resource | Link |
|----------|------|
| **Run** | [`simple_ontology_demo.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/simple_ontology_demo.py) |
| **Rule YAML** (cookbook-style `inputs`) | [`simple_ontology_rule.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/simple_ontology_rule.yaml) |
| Walkthrough | [`README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/README.md) |
| Top-level index | [`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md) |

AHU / RTU notebooks and sample rules — **`examples/AHU/`** ([folder on GitHub](https://github.com/bbartling/open-fdd/tree/master/examples/AHU)):

| Resource | Link |
|----------|------|
| Sample YAML rules | [`rules/sensor_bounds.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/rules/sensor_bounds.yaml), [`rules/sensor_flatline.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/rules/sensor_flatline.yaml), [`rules/sat_operating_band.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/rules/sat_operating_band.yaml) |
| Notebooks | [`RTU11_standardized_refactored.ipynb`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/RTU11_standardized_refactored.ipynb), [`RTU7_standardized_refactored.ipynb`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/RTU7_standardized_refactored.ipynb), [`RTU7_machine_learning.ipynb`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/RTU7_machine_learning.ipynb) |
| Sample CSV | [`RTU11.csv`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/RTU11.csv), [`AHU7.csv`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/AHU7.csv) |
| Helpers | [`openfdd_notebook_helpers_v2.py`](https://github.com/bbartling/open-fdd/blob/master/examples/AHU/openfdd_notebook_helpers_v2.py) |

More narrative (Docker **`--mode engine`**, IoT pipelines, **`column_map` policy**): [Engine-only & IoT pipelines](howto/engine_only_iot). Curated doc links: [Examples (repository)](examples).

---

## See also

- [Getting started](getting_started) — **`RuleRunner`** + **`column_map`** in one example
- [Engine-only & IoT pipelines](howto/engine_only_iot) — integration patterns and resolver priority
- [Fault rules overview](rules/overview) — YAML **`inputs`** and Brick-oriented keys
- [Expression rule cookbook](expression_rule_cookbook) — expression rules (same keying model)
- [Examples (repository)](examples) — notebooks and CSVs under **`examples/AHU/`**
