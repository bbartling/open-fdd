---
title: Column map & resolvers
nav_order: 3
description: "Map Brick-style rule input names to DataFrame columns: dict, TTL, manifest, or composite resolvers."
---

# Column map & resolvers

YAML rules name their **`inputs`** with **Brick-style logical keys** (for example `Supply_Air_Temperature_Sensor`). Your **`pandas`** frame uses **your** column names (`sat`, `AHU1_SupplyTemp`, …).

**`column_map`** is the bridge: `dict[str, str]` where each **key** is the **same string the rule YAML uses** (the logical / Brick-class side), and each **value** is the **actual `DataFrame` column name**.

Pass it to **`RuleRunner.run(..., column_map=...)`**. You can build that dict by hand, load it from a manifest, derive it from a Brick **`.ttl`** file, or **merge** several sources with a composite resolver.

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

## 2. Brick TTL (`BrickTtlColumnMapResolver`)

If you have a Brick **`.ttl`** model (same general idea as a stack deployment’s RDF graph), **`BrickTtlColumnMapResolver`** runs the same SPARQL-based mapping logic the platform uses when resolving points from TTL.

```python
from pathlib import Path
from open_fdd.engine.column_map_resolver import BrickTtlColumnMapResolver

cm = BrickTtlColumnMapResolver().build_column_map(ttl_path=Path("model.ttl"))
runner.run(df, column_map=cm)
```

Install: **`pip install "open-fdd[brick]"`** (pulls **rdflib** and compatible **pyparsing** pins).

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

Run multiple resolvers **in order**; for each logical key, the **first resolver that defines it wins** (for example: TTL for most points, manifest only for gaps).

```python
from pathlib import Path
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

**Security:** There is **no** env-driven “import a resolver class by string” — compose resolvers in code or a small startup script.

---

## Examples in the repo

Workshop — **`examples/column_map_resolver_workshop/`** ([folder on GitHub](https://github.com/bbartling/open-fdd/tree/master/examples/column_map_resolver_workshop)):

| Resource | Link |
|----------|------|
| **CLI (`brick` / `haystack` / `dbo` / `223p` / `minimal`)** | [`run_ontology_demo.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/run_ontology_demo.py) |
| Walkthrough | [`README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/README.md) |
| Top-level index | [`examples/README.md`](https://github.com/bbartling/open-fdd/blob/master/examples/README.md) |
| One-shot script (manifest + **`RuleRunner`**) | [`demo_one_shot.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_one_shot.py) |
| Multi-ontology illustration | [`demo_multi_ontology_illustration.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_multi_ontology_illustration.py) |
| Rules (Brick + Haystack + DBO + 223P) | [`demo_rule.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_rule.yaml), [`demo_rule_haystack.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_rule_haystack.yaml), [`demo_rule_dbo.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_rule_dbo.yaml), [`demo_rule_223p.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_rule_223p.yaml) |
| Manifests | [`manifest_minimal.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_minimal.yaml), [`manifest_brick.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_brick.yaml), [`manifest_haystack.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_haystack.yaml), [`manifest_dbo.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_dbo.yaml), [`manifest_223p.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_223p.yaml) (illustrative slashes), [`manifest_223p_safe.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_223p_safe.yaml) (expression-safe) |

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
