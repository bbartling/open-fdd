---
title: Data modeling & platform docs
nav_order: 7
has_children: false
---

# Data modeling and full-stack docs

**Brick, 223P, SPARQL, CRUD APIs, Docker Compose, and lab automation** for Open-FDD as a **deployed platform** now live in a separate repository:

**[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**

That site documents how the stack uses this **`open-fdd`** PyPI package **under the hood** (`RuleRunner`, YAML rules, pandas).

---

## In *this* repository (rules engine only)

- **[Column map resolvers](../column_map_resolvers)** — map **Brick**, **Haystack**, **DBO**, **223P**, or vendor labels to DataFrame columns (dict, manifest, composite resolvers).
- **[Expression rule cookbook](../expression_rule_cookbook)** — fault logic on pandas, including schedule and weather gates via **`params.schedule`** / **`params.weather_band`**.
- **`examples/column_map_resolver_workshop/`** — runnable **ontology-agnostic** demo (`simple_ontology_demo.py`).

Semantic modeling and TTL/SQL integration are **not** part of the **`open-fdd`** wheel; keep RDF/graph work in your services or in **open-fdd-afdd-stack** as documented there.
