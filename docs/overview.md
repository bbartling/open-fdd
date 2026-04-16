---
title: System Overview
nav_order: 2
---

# System overview

**Open-FDD** (package name **`open-fdd`**, import **`open_fdd`**) is a **library** for running **fault detection and diagnostics (FDD)** rules on **pandas** `DataFrame`s. Rules are authored in **YAML**; the core type is **`RuleRunner`** in **`open_fdd.engine`**.

---

## Data flow

1. **Your pipeline** loads or builds a time-indexed (or otherwise keyed) `DataFrame` of sensor or calculated points.
2. **Column mapping** connects logical point names used in rules to actual column names (dict, manifest YAML, or custom resolver).
3. **`RuleRunner`** evaluates configured checks and returns **fault results** compatible with **`open_fdd.schema`**.

There is no required database, HTTP service, or message bus in this repository—the engine runs wherever you import it.

---

## Related topics

- [Modular architecture](modular_architecture) — how rule types and resolvers fit together
- [Rules overview](rules/overview)
- [Engine API](api/engine)
