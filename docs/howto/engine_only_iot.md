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

**`column_map`** (Brick class name → your column):

```python
column_map = {
    "Supply_Air_Temperature_Sensor": "sat",
    "Outside_Air_Temperature_Sensor": "oat",
}
```

Minimal example rule (cookbook-style multi-ontology **`inputs`**): [`simple_ontology_rule.yaml`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/simple_ontology_rule.yaml). The **`expression`** always uses the **input key** (e.g. **`Supply_Air_Temperature_Sensor`**), not the ontology alias strings.

---

## Haystack-flavored names

Haystack gives you **tags or refs**; you still choose **stable slugs** for **`column_map`** keys. If your rule uses **cookbook-style** **`inputs`** (Brick input key + **`haystack:`** alias on the same block), the **`expression`** still names the **input key**; **`column_map`** uses the Haystack slug:

```python
column_map = {
    "discharge_air_temp_sensor": "sat",
    "outside_air_temp_sensor": "oat",
}
```

See [`simple_ontology_demo.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/simple_ontology_demo.py) (Haystack row).

---

## DBO / Google Digital Buildings–style names

Illustrative **type-style** keys (your site may differ). Physical columns are still **`sat`** / **`oat`**.

**`column_map`** (DBO-style type name → column):

```python
column_map = {
    "SupplyAirTemperatureSensor": "sat",
    "OutsideAirTemperatureSensor": "oat",
}
```

With cookbook-style **`inputs`**, the **`expression`** still uses the **input key**; **`column_map`** matches the **`dbo:`** label. See **`simple_ontology_demo.py`** (DBO row).

---

## 223P-scoped names

223P graphs often need **equipment + connection** in the label so “supply air temp” is not ambiguous. Your **graph** might use paths like **`AHU-1 / supply_air_temp`**; when you feed **`RuleRunner`**, you still emit a **`column_map`** from **whatever string you use as the rule input key** → **`sat`** / **`oat`**.

**Illustrative map** (slash-style labels — often **not** valid in **`type: expression`** rules):

```python
column_map = {
    "AHU-1/supply_air_temp": "sat",
    "AHU-1/outside_air_temp": "oat",
}
```

**Important — `type: expression`:** Variables inside **`expression`** come from **input keys**, which must be **valid Python identifiers**. Put scoped graph strings on **`s223:`** / **`223p:`** in **`inputs`** and key **`column_map`** by those strings (see **`simple_ontology_rule.yaml`**). Use **safe slugs** (underscores), not slashes, when a label must double as an input key.

Example safe keys (match **`s223:`** / **`223p:`** on **`inputs`** — see **`simple_ontology_rule.yaml`**):

```python
column_map = {"bldg1_supply_air_temperature_sensor": "sat"}
# or
column_map = {"ahu1_supply_air_temp_223p": "sat"}
```

---

## Run **`RuleRunner`**

From a rule file plus a **`column_map`** dict (or load a manifest with **`load_column_map_manifest`**):

```python
from pathlib import Path
from open_fdd.engine.runner import RuleRunner, load_rule

root = Path("examples/column_map_resolver_workshop")  # adjust to your clone
rules = [load_rule(root / "simple_ontology_rule.yaml")]
runner = RuleRunner(rules=rules)

column_map = {"discharge_air_temp_sensor": "sat"}  # Haystack-style key → column

out = runner.run(
    df,
    timestamp_col="timestamp",
    column_map=column_map,
    params={"units": "imperial"},
    skip_missing_columns=True,
)
```

**Minimal demo:** [`simple_ontology_demo.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/simple_ontology_demo.py) prints one run per ontology key style using the same rule YAML.

---

## Manifests on disk, Brick TTL, composites

Covered step-by-step on **[Column map & resolvers](../column_map_resolvers)**:

- **YAML/JSON manifest** — `ManifestColumnMapResolver`, `load_column_map_manifest`
- **Brick `.ttl` file** — handled by the **AFDD stack** (`openfdd_stack.platform.brick_ttl_resolver`); **`pip install open-fdd`** alone uses manifests or a plain dict
- **TTL + small override file** — `FirstWinsCompositeResolver` (first resolver wins per key)

Implementation: [`open_fdd/engine/column_map_resolver.py`](https://github.com/bbartling/open-fdd/blob/master/open_fdd/engine/column_map_resolver.py). Workshop: **[`examples/column_map_resolver_workshop/`](https://github.com/bbartling/open-fdd/tree/master/examples/column_map_resolver_workshop)** ([README](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/README.md)).

---

## Docker **`--mode engine`** (different repo)

**Postgres, `fdd-loop`, weather worker, and Compose “engine” mode** are part of the **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** Docker platform, not something you run from the **`open-fdd`** library repo alone. That path is for teams who want **scheduled FDD inside Compose** with the same database pattern as the full product.

- **Modes and services:** [Modular architecture](https://bbartling.github.io/open-fdd-afdd-stack/modular_architecture) (AFDD stack docs).
- **Stack setup:** [Getting started](https://bbartling.github.io/open-fdd-afdd-stack/getting_started) on the stack site.

If your data lives in **Snowflake, BigQuery, a lake, or flat files**, stay on **`RuleRunner` + `DataFrame`** above — no requirement to use that Docker slice.

---

## See also

- [Getting started](../getting_started) — install, extras, one complete **`RuleRunner`** example
- [Expression rule cookbook](../expression_rule_cookbook) — authoring **`expression`** rules
- [Examples (repository)](../examples) — **`AHU/`** notebooks and CSVs
- [Fault rules overview](../rules/overview) — YAML **`inputs`**, **`flag`**, types

Maintainers: alternate PyPI package name and release alignment — [PyPI releases (`open-fdd`)](https://bbartling.github.io/open-fdd-afdd-stack/howto/openfdd_engine_pypi) (stack docs).
