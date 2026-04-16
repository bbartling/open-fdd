---
title: RDF, Brick, and optional BACnet-shaped metadata
nav_order: 2
parent: Concepts
---

# RDF, Brick, and optional BACnet-shaped metadata

The **`open-fdd`** wheel evaluates rules on **pandas** using **`column_map`** (dict or manifest). **Brick**, **223P**, **Haystack**, **DBO**, and BACnet-shaped **TTL** are **not** parsed inside this package—you build the bridge in your pipeline or use a platform that does.

**Where the full graph story lives:** **[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)** (CRUD, SPARQL, import/export, compose, hosted services).

**Here in this repo:** see **[Column map resolvers](column_map_resolvers)** and the **[Expression rule cookbook](expression_rule_cookbook)** for ontology-agnostic rule authoring.
