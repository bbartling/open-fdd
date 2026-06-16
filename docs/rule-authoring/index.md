---
title: Rule authoring (v1)
parent: Rule Cookbook
nav_order: 1
---

# Rule authoring (stable v1)

Open-FDD **v1 executable FDD** runs on **PyArrow tables** at the edge. Optional **DataFusion SQL** covers simple, stateless rules. The old **pandas row-loop / YAML expression** runtime is **retired** for production batch FDD.

| Page | Purpose |
|------|---------|
| [PyArrow vs DataFusion SQL]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#pyarrow-vs-datafusion-sql) | Decision table — start here |
| [Arrow rule contract]({{ "/rule-authoring/arrow-rule-contract/" | relative_url }}) | `apply_faults_arrow`, `ArrowRuleResult`, confirmation |
| [Data types & units]({{ "/rule-authoring/data-types-and-units/" | relative_url }}) | Table shape, nulls, commands, sensor profiles |
| [Legacy pandas parity]({{ "/rule-authoring/legacy-pandas-parity/" | relative_url }}) | Gist FC1–FC15 → modern Arrow mapping |
| [Rust readiness]({{ "/rule-authoring/rust-readiness/" | relative_url }}) | Checklist for portable rules |
| [Expression cookbook]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}) | Sensor profiles, GL36 patterns, starter pack |
| [DataFusion SQL rules]({{ "/datafusion-sql-rules/" | relative_url }}) | Optional SQL backend install & safety |

## YAML in the repo today

Two different YAML uses — do not conflate them:

| YAML location | Role in v1 | Executable on edge? |
|---------------|------------|---------------------|
| `open_fdd/faults/catalog/*.yaml` | **Fault-code metadata** — letter codes, descriptions, standards crosswalk | No — catalog only |
| `open_fdd/default_rules/**/*.yaml` | **Starter rule metadata** — inputs, params, legacy expression text for migration reference | **No** — translate to `rules_py` Arrow modules |
| Rule Lab saved rules (`workspace/data/rules_py/`) | **Production rules** — `apply_faults_arrow` or `backend: datafusion_sql` | **Yes** |

**Retired:** pandas-era `type: expression` / `type: hunting` packs executed by `open_fdd.engine.RuleRunner`. That engine is not shipped on PyPI 3.x.

## Install extras (packaging)

| Extra | Purpose |
|-------|---------|
| `pip install open-fdd` | PyArrow runtime, lint, tests |
| `pip install 'open-fdd[datafusion]'` | Optional DataFusion SQL backend (`datafusion>=40`) |
| `pip install 'open-fdd[pandas]'` | **Dev/central analytics only** — not edge FDD |

See [pyproject.toml](https://github.com/bbartling/open-fdd/blob/master/pyproject.toml) — the `datafusion` optional dependency group is defined and matches docs.

## Legacy reference

The historical pandas fault classes live in this gist (reference only):

[bbartling/11cb1cb1295a1bfba5c167efa02122ef](https://gist.github.com/bbartling/11cb1cb1295a1bfba5c167efa02122ef)

Use the [legacy parity matrix]({{ "/rule-authoring/legacy-pandas-parity/" | relative_url }}) for migration — not the gist — when binding modern fault codes and tests.
