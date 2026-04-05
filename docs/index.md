---
title: Home
nav_order: 1
description: "Install open-fdd from PyPI, run YAML fault rules on pandas DataFrames. Links to the full Docker AFDD stack."
---

# Open-FDD engine

{: .fs-6 .fw-400 }
**`open-fdd`** on [PyPI](https://pypi.org/project/open-fdd/) is a small Python library: load **YAML** fault rules, run them on **pandas** `DataFrame`s, read boolean **`*_flag`** columns. If you already use notebooks, CSV exports, or a warehouse, you only need **`pip install open-fdd`**.

> **Full platform** — Docker Compose, API, BACnet, React UI, knowledge graph, `bootstrap.sh` — lives in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.  
> **Docs:** [AFDD stack (GitHub Pages)](https://bbartling.github.io/open-fdd-afdd-stack/) · [Repo](https://github.com/bbartling/open-fdd-afdd-stack)

---

## Start here

| If you… | Read |
|---------|------|
| Want the fastest path from install to `RuleRunner` | [Getting started](getting_started) |
| Map Brick / ontology names to your column names | [Column map & resolvers](column_map_resolvers) |
| Run rules on CSV or batch data (no database) | [Getting started](getting_started) · [Examples](examples) |
| Author or tune YAML rules | [Fault rules](rules/overview) · [Expression cookbook](expression_rule_cookbook) |
| Browse workshop-style examples | [Examples in this repo](examples) |
| Use Docker **`--mode engine`** without the full UI | [Engine-only / IoT](howto/engine_only_iot) |

---

## Contributors

[Contributing](contributing) · [Developer guide](appendix/developer_guide) · [Tests (repo root)](https://github.com/bbartling/open-fdd/blob/master/TESTING.md)

---

## License

MIT — [open-fdd on GitHub](https://github.com/bbartling/open-fdd).
