---
title: Home
nav_order: 1
---

# Open-FDD engine (PyPI)

**`open-fdd`** is a Python library: load YAML fault rules, run them on **pandas** `DataFrame`s, get boolean fault columns. If you already use notebooks, CSVs, or a warehouse for time-series, you only need **`pip install open-fdd`**.

The **Docker AFDD platform** (Compose, API, BACnet, React UI, graph, `bootstrap.sh`) is documented separately:

**[→ AFDD stack documentation](https://bbartling.github.io/open-fdd-afdd-stack/)** · [GitHub](https://github.com/bbartling/open-fdd-afdd-stack) · [PyPI `open-fdd`](https://pypi.org/project/open-fdd/)

---

## Start here

| If you… | Read |
|--------|------|
| Want the smallest path from install to `RuleRunner` | [Getting started](getting_started) |
| Have your own columns / ontologies (not only Brick TTL) | [Column map & resolvers](column_map_resolvers) |
| Need CSV or batch workflows | [Standalone CSV / pandas](standalone_csv_pandas) |
| Author or tune YAML rules | [Fault rules](rules/overview) · [Expression cookbook](expression_rule_cookbook) |
| Want workshop-style examples | [Examples in this repo](examples) |
| Run FDD inside Docker but not the full UI stack | [Engine-only / IoT note](howto/engine_only_iot) (points at stack `--mode engine`) |

---

## Contributors

[Contributing](contributing) · [Developer guide](appendix/developer_guide) · [Tests (repo root)](https://github.com/bbartling/open-fdd/blob/master/TESTING.md)

---

## License

MIT — [open-fdd on GitHub](https://github.com/bbartling/open-fdd).
