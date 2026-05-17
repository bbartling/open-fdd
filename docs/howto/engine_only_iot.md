---
title: Engine-only deployment and external IoT pipelines
parent: How-to Guides
nav_order: 21
---

# Engine-only deployment and external IoT pipelines

> **Library-only (`pip install "open-fdd[engine]"`):** See the **[engine documentation](https://bbartling.github.io/open-fdd/)** — [Getting started](https://bbartling.github.io/open-fdd/getting_started), [Expression rule cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook), [Column map & resolvers](https://bbartling.github.io/open-fdd/column_map_resolvers), and this page for pandas integrators.

Integrators who already run **data collection** (historians, MQTT, BAS exports) and their own **modeling** can add **FDD** with **`open_fdd.engine.RuleRunner`** and the same **YAML** rules you would use in any other context.

> **Package names:** The rules code lives under **`open_fdd.engine`**. The optional **`openfdd-engine`** package (**`openfdd_engine`**) is a thin re-export — not a different engine. See [The optional openfdd-engine package](openfdd_engine).

---

## Library path — same YAML, any DataFrame

The rule runner is **`open_fdd.engine.runner.RuleRunner`**. It loads **`.yaml`** rule files (`type: bounds|flatline|expression|…`, `inputs`, `params`, …). Authoring references:

- [Expression rule cookbook](../expression_rule_cookbook)
- Examples under **`examples/`** in the repository

**Minimal integration pattern**

1. Build a **pandas** `DataFrame` whose columns are your sensor traces (and optional timestamp column).
2. Point **`RuleRunner`** at a directory of `.yaml` files **or** pass **`rules=[...]`** dicts.
3. Call **`run(df, timestamp_col=..., skip_missing_columns=True, column_map={...})`**.
4. Read boolean **`*_flag`** columns and related outputs per the rule definitions.

**`column_map`** — when your naming layer uses Brick-style or vendor tags but DataFrame columns differ (for example `temp_sa` vs a Brick class label), pass **`column_map`** from logical key to column name. See **`RuleRunner.run`** in **`open_fdd/engine/runner.py`**.

### Bring your own `column_map` or resolver

1. **Plain dict** — `column_map: dict[str, str]` (rule input key → DataFrame column). Pass to **`RuleRunner.run(..., column_map=column_map)`**.
2. **Brick TTL + SPARQL** — The **`open-fdd`** wheel does **not** include **rdflib**. If you resolve points from TTL yourself, install **rdflib** in your environment and build a dict before calling **`RuleRunner`**.
3. **Custom `ColumnMapResolver`** — Implement **`build_column_map(*, ttl_path: Path) -> dict[str, str]`** per **`open_fdd.engine.column_map_resolver`**, or use **`ManifestColumnMapResolver`** / **`FirstWinsCompositeResolver`** for manifest-driven maps.

**Priority / policy:** The engine uses **one** `column_map` per run. Resolve ambiguity in your pipeline before calling **`RuleRunner`**.

### Manifest file + composite priority

- **`load_column_map_manifest(path)`** — reads **`.json`** or **`.yaml`**. Accepts a flat object or a nested **`column_map:`** mapping.
- **`ManifestColumnMapResolver(path)`** — exposes the manifest via the resolver protocol.
- **`FirstWinsCompositeResolver(r1, r2, ...)`** — first resolver to supply a key wins.

**Examples:** **`examples/column_map_resolver_workshop/`** — **`simple_ontology_demo.py`**.

**Install**

```bash
pip install "open-fdd[engine]"
# or from a checkout (dev extras include PyYAML and pydantic for rules):
pip install -e ".[dev]"
```

---

## Standalone playground (optional)

- **`examples/engine_iot_playground/`** — README, rules, sample CSV, **`run_demo.py`**, notebook.

---

## Summary

| Approach | You bring | Open-FDD provides |
|----------|-----------|---------------------|
| **`RuleRunner` in Python** | DataFrame + YAML rules | Fault columns and structured outputs |
| **Batch / notebook** | CSV or query results | Same semantics as any other caller |

For package layout, see [Modular architecture](../modular_architecture).
