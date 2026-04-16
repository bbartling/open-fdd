---
title: API Reference
parent: Appendix
nav_order: 0
nav_exclude: true
---

# API reference

This repository ships the **`open_fdd`** **Python API** only. There is **no** bundled HTTP service.

---

## Engine (canonical)

See **[Engine API](../api/engine)** for:

- **`RuleRunner`**
- **`load_rule`**, **`bounds_map_from_rule`**
- **Column map resolvers** and manifest loading

The OpenAPI/Swagger style **REST** surface described in older revisions is **not** part of this tree.

---

## Optional distribution

The **`openfdd-engine`** package (under **`packages/openfdd-engine/`**) re-exports a subset of the engine API and depends on **`open-fdd`** from PyPI. Most users should **`pip install open-fdd`** only.
