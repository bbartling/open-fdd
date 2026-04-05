---
title: Engine-only & IoT pipelines
nav_order: 5
description: "Build a pandas DataFrame, map Haystack / Brick / DBO / 223P names to columns, run RuleRunner — without the Docker stack."
---

# Engine-only and IoT-style use

This page is for people who already have **time-series data** (historian export, MQTT pipeline, warehouse query, CSV) and want **`open-fdd`** to evaluate **YAML rules** on a **`pandas.DataFrame`**.

You do **not** need Postgres, TimescaleDB, or Docker for that path.

> **`from open_fdd import RuleRunner`** after **`pip install open-fdd`**. Rules live under **`open_fdd.engine`**; see [Getting started](../getting_started) for a full walkthrough.

---

## The only idea you need

1. Build a **wide** table: one row per time step, one column per sensor (plus optional **`timestamp`**).
2. Your YAML rules talk in **logical names** (whatever you put in `inputs` and in **`expression`** — e.g. a Brick class name, a Haystack slug you invented, a 223P-scoped label).
3. **`column_map`** is a dict: **`{ logical_name: actual_column_name_in_df }`**. It tells **`RuleRunner`** which physical column to use when the rule says a given name.

The **left-hand keys** of **`column_map`** must match the names your **rule YAML** uses. The **right-hand values** are whatever your pipeline actually named the columns (`sat`, `AHU1_SA_T`, …).

---

## One `DataFrame` you can reuse

Most examples below use the same small frame: two sensors as columns **`sat`** and **`oat`**, plus **`timestamp`**.

```python
import pandas as pd

df = pd.DataFrame(
    {
        "timestamp": pd.date_range("2025-01-01", periods=6, freq="h", tz="UTC"),
        "sat": [72.0, 74.0, 76.0, 105.0, 70.0, 71.0],
        "oat": [35.0, 36.0, 38.0, 40.0, 34.0, 33.0],
    }
)
```

Your real job is whatever produces **`df`** (SQL, Parquet, MQTT aggregate, …). **`open-fdd`** only cares that the columns exist.

---

## Brick-style names (common default)

Rules often use **Brick class local names** like **`Supply_Air_Temperature_Sensor`**. Your warehouse columns stay short (**`sat`**, **`oat`**).

**`column_map`** (same as [`manifest_brick.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_brick.yaml)):

```python
column_map = {
    "Supply_Air_Temperature_Sensor": "sat",
    "Outside_Air_Temperature_Sensor": "oat",
}
```

Use with rule YAML whose **`inputs`** and **`expression`** use those same strings. Example rule in the repo: [`demo_rule.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_rule.yaml).

---

## Haystack-flavored names

Haystack gives you **tags or refs**; you still choose **stable slugs** for rule logic. Here the logical keys are slug-style names; the frame columns stay **`sat`** / **`oat`**.

**`column_map`** (same shape as [`manifest_haystack.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_haystack.yaml)):

```python
column_map = {
    "discharge_air_temp_sensor": "sat",
    "outside_air_temp_sensor": "oat",
}
```

Your **rule YAML** must use **`discharge_air_temp_sensor`** (and **`outside_air_temp_sensor`** if needed) in **`inputs`** and in the **`expression`**, not the Brick names — unless you also change the map. One rule, one naming convention.

---

## DBO / Google Digital Buildings–style names

Illustrative **type-style** keys (your site may differ). Physical columns are still **`sat`** / **`oat`**.

**`column_map`** (same as [`manifest_dbo.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_dbo.yaml)):

```python
column_map = {
    "SupplyAirTemperatureSensor": "sat",
    "OutsideAirTemperatureSensor": "oat",
}
```

Again: **rule YAML** uses these tokens in **`inputs`** / **`expression`**.

---

## 223P-scoped names

223P graphs often need **equipment + connection** in the label so “supply air temp” is not ambiguous. Your **graph** might use paths like **`AHU-1 / supply_air_temp`**; when you feed **`RuleRunner`**, you still emit a **`column_map`** from **whatever string you use as the rule input key** → **`sat`** / **`oat`**.

**Illustrative map** (same idea as [`manifest_223p.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/manifest_223p.yaml)):

```python
column_map = {
    "AHU-1/supply_air_temp": "sat",
    "AHU-1/outside_air_temp": "oat",
}
```

**Important — `type: expression`:** Names in **`inputs`** become variables inside the **`expression`** string (via **`pandas.eval` / `eval`**). They must be **valid Python identifiers** (use **`ahu1_supply_air_temp`**, not **`AHU-1/supply_air_temp`**, in rules that use **`expression`**). **`bounds`** and **`flatline`** do not **`eval`** those keys the same way, so slash-heavy labels are less of a problem there — when in doubt, **normalize** graph labels to safe slugs for expression rules.

Example safe variant for the same physical columns:

```python
column_map = {
    "ahu1_supply_air_temp": "sat",
    "ahu1_outside_air_temp": "oat",
}
```

---

## Run **`RuleRunner`**

From a manifest file (JSON or YAML with a top-level **`column_map:`** or flat map):

```python
from pathlib import Path
from open_fdd import RuleRunner
from open_fdd.engine.column_map_resolver import load_column_map_manifest
from open_fdd.engine.runner import load_rule

root = Path("examples/column_map_resolver_workshop")  # adjust to your clone
column_map = load_column_map_manifest(root / "manifest_brick.yaml")
rules = [load_rule(root / "demo_rule.yaml")]
runner = RuleRunner(rules=rules)

out = runner.run(
    df,
    timestamp_col="timestamp",
    column_map=column_map,
    params={"units": "imperial"},
    skip_missing_columns=True,
)
```

**Easiest — pick Brick, Haystack, DBO, or 223P from the shell:** [`run_ontology_demo.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/run_ontology_demo.py) (e.g. **`python examples/column_map_resolver_workshop/run_ontology_demo.py haystack`**; use **`--list`** for modes).

Single-path script: [`demo_one_shot.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_one_shot.py) (minimal manifest + **`demo_high_sat_flag`**).

Static comparisons of ontology **key shapes** (no full rule run): [`demo_multi_ontology_illustration.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/demo_multi_ontology_illustration.py).

---

## Manifests on disk, Brick TTL, composites

Covered step-by-step on **[Column map & resolvers](../column_map_resolvers)**:

- **YAML/JSON manifest** — `ManifestColumnMapResolver`, `load_column_map_manifest`
- **Brick `.ttl` file** — `BrickTtlColumnMapResolver` (**`pip install "open-fdd[brick]"`**)
- **TTL + small override file** — `FirstWinsCompositeResolver` (first resolver wins per key)

Implementation: [`open_fdd/engine/column_map_resolver.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/engine/column_map_resolver.py). Workshop: **[`examples/column_map_resolver_workshop/`](https://github.com/bbartling/open-fdd/tree/master/examples/column_map_resolver_workshop)** ([README](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/README.md)).

---

## Docker **`--mode engine`** (different repo)

**Postgres, `fdd-loop`, weather worker, and `./scripts/bootstrap.sh --mode engine`** are part of the **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** Docker platform, not something you run from the **`open-fdd`** library repo alone. That path is for teams who want **scheduled FDD inside Compose** with the same database pattern as the full product.

- **Modes and services:** [Modular architecture](https://bbartling.github.io/open-fdd-afdd-stack/modular_architecture) (AFDD stack docs).
- **Bootstrap:** [Getting started](https://bbartling.github.io/open-fdd-afdd-stack/getting_started) on the stack site.

If your data lives in **Snowflake, BigQuery, a lake, or flat files**, stay on **`RuleRunner` + `DataFrame`** above — no requirement to use that Docker slice.

---

## See also

- [Getting started](../getting_started) — install, extras, one complete **`RuleRunner`** example
- [Expression rule cookbook](../expression_rule_cookbook) — authoring **`expression`** rules
- [Examples (repository)](../examples) — **`AHU/`** notebooks and CSVs
- [Fault rules overview](../rules/overview) — YAML **`inputs`**, **`flag`**, types

Maintainers: alternate PyPI package name and release alignment — [PyPI releases (`open-fdd`)](https://bbartling.github.io/open-fdd-afdd-stack/howto/openfdd_engine_pypi) (stack docs).
