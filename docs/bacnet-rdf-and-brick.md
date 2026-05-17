---
title: Ontology labels and column_map
nav_order: 2
parent: Concepts
---

# Ontology labels and column_map

The **`open-fdd`** wheel evaluates rules on **pandas** using **`column_map`** (dict or manifest). **Brick**, **223P**, **Haystack**, **DBO**, and BACnet-shaped metadata are **not** parsed inside this package — you build the bridge in your pipeline.

**Here in this repo:** see **[Column map resolvers](column_map_resolvers)** and the **[Expression rule cookbook](expression_rule_cookbook)** for ontology-agnostic rule authoring.

Optional per-input fields **`brick`**, **`haystack`**, **`dbo`**, **`s223`**, and **`223p`** are matched against **`column_map`** in that order (**first match wins**). See **`examples/column_map_resolver_workshop/`** for a minimal end-to-end demo.
