---
title: Home
nav_order: 1
description: "Open-FDD rules engine: fault detection on pandas DataFrames from YAML rules. Published as open-fdd on PyPI."
---

# Open-FDD

The **`open-fdd`** package is a **pandas-first rules engine** for building science and HVAC workflows: define fault checks in **YAML**, map columns on a **pandas** `DataFrame`, and run them with **`RuleRunner`**.

**PyPI install (bare):** `pip install open-fdd` — **pandas** only.

**Run YAML rules:** `pip install "open-fdd[engine]"` — adds **PyYAML** and **pydantic** for rule loading and validation. NumPy is pulled in through pandas.

For a full deployed platform (APIs, Docker, Brick/223P services), see **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)**.

---

## What it does

- **Loads** rule definitions from YAML (bounds, flatline, hunting, expressions, schedules, weather gates, …).
- **Maps** ontology or vendor labels to DataFrame columns via **`column_map`**.
- **Runs** checks on time-indexed data and returns boolean **`*_flag`** columns plus optional analytics.

Bring your own data: CSV exports, historian extracts, or notebooks. The engine does **not** connect to databases or field buses by itself.

## Behind the firewall; cloud export is vendor-led
{: #behind-the-firewall-cloud-export-is-vendor-led }

Open-FDD does not push data to the cloud. Cloud FDD, MSI, and commissioning vendors run their own export jobs on the building or OT network, pull from your Open-FDD API over the LAN, and forward results to their platform. See [Cloud export example](concepts/cloud_export).

---

## Quick start

```bash
pip install "open-fdd[engine]"
```

```python
from open_fdd.engine import RuleRunner

runner = RuleRunner(rules_path="path/to/rules")
df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})
```

From a git checkout:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest open_fdd/tests/engine
```

---

## Documentation

| Section | Description |
|---------|-------------|
| [Expression rule cookbook](expression_rule_cookbook) | **Primary reference** — expressions, gates, scaling |
| [Getting started](getting_started) | Install extras, tests, examples |
| [Rules overview](rules/overview) | Rule types and YAML structure |
| [Column map resolvers](column_map_resolvers) | Manifests and composite maps |
| [Engine API](api/engine) | `RuleRunner`, loaders, resolvers |
| [How-to guides](howto/index) | PyPI releases, verification, operations |
| [Appendix](appendix/index) | Technical reference, developer guide |

---

## License

MIT — see the repository **`LICENSE`** file.
