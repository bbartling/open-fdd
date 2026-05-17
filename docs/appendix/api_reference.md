---
title: API Reference
parent: Appendix
nav_order: 0
nav_exclude: true
---

# API reference

This repository ships **`open_fdd.engine`** and **`open_fdd.reports`** on PyPI. There is **no** bundled HTTP service.

---

## Engine

See **[Engine API](../api/engine)** for **`RuleRunner`**, **`load_rule`**, and column-map resolvers.

Install: `pip install "open-fdd[engine]"`.

---

## Reports

See **[Reports API](../api/reports)** for fault summaries, plots, and optional Word export.

Install: `pip install "open-fdd[reports]"` for plots; `pip install python-docx` for `.docx`.

---

## Schema

**`open_fdd.schema`** — **`FDDResult`**, **`FDDEvent`**, helpers to convert runner output to rows. Used by the engine; optional for your own storage layer.

---

## Optional distribution

**`openfdd-engine`** (`packages/openfdd-engine/`) re-exports a subset of **`open_fdd.engine`**. Most users should **`pip install open-fdd`** only.
