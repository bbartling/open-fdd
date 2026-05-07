---
title: Home
nav_order: 1
description: "Open-FDD rules engine: fault detection on pandas DataFrames from YAML rules. Published as open-fdd on PyPI."
---

# Open-FDD

The **`open-fdd`** package (**`open_fdd/`** in this repository) is a **rules engine** for building science and HVAC workflows: you define fault checks in **YAML**, map columns on a **pandas** `DataFrame`, and run them with **`RuleRunner`**. It is published to **[PyPI](https://pypi.org/project/open-fdd/)** as a small, dependency-conscious wheel (pandas, NumPy, PyYAML, pydantic).

**Full platform** (data model, APIs, Docker, Brick/223P tooling beyond `column_map`): **[open-fdd-afdd-stack — `docs/`](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)** — it uses this library under the hood.

---

## What it does

- **Loads** rule definitions from YAML (bounds, flatline, hunting, expressions, schedules, weather gates, …).
- **Maps** **Brick**, **Haystack**, **DBO**, **223P**, or vendor names to DataFrame columns via **`column_map`** (dict, manifest, or composite resolvers) — same YAML can target different ontologies by swapping the map.
- **Runs** checks over time-indexed or ordered data and returns structured **fault results** (see **`open_fdd.schema`**).

Desktop mode is also available and under active construction in this repository. The current desktop path uses local Feather-backed ingestion plus optional batched rule execution for large datasets.

Bring your own data: CSV exports, historian extracts, lab benches, or notebooks. The engine does **not** connect to databases or field buses by itself.

---

## Quick start

```bash
pip install open-fdd
```

From a git checkout:

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

See **[Getting started](getting_started)** and **`examples/README.md`** in the repository for runnable entrypoints.

---

## Behind the firewall; cloud export is vendor-led
{: #behind-the-firewall-cloud-export-is-vendor-led}

Open-FDD is meant to run **on the building network**. Vendors and MSI platforms that need cloud analytics **pull** from your deployment over the LAN; Open-FDD does not push to their cloud for you. See **[Cloud export example](concepts/cloud_export)** for a sample integration script.

---

## Documentation

| Section | Description |
|---------|-------------|
| [Getting started](getting_started) | Install, tests, examples |
| [Rules overview](rules/overview) | Rule types and YAML structure |
| [Expression rule cookbook](expression_rule_cookbook) | Expressions, ontology labels, schedule & weather gates |
| [Column map resolvers](column_map_resolvers) | Brick / Haystack / DBO / 223P → columns |
| [Engine API](api/engine) | `RuleRunner`, loaders, resolvers |
| [Desktop app (under construction)](howto/desktop_app) | Local gateway (`open_fdd.gateway`), MCP, React UI, Feather storage, batched rule runs |
| [Data modeling & platform (pointer)](modeling/index) | Full stack docs live in **open-fdd-afdd-stack** |
| [Open-FDD Codex architecture](open-fdd-codex-architecture) | Built-in Codex CLI path, host startup order, and gateway/agent responsibilities. |
| [How-to guides](howto/index) | PyPI releases, verification, operations |
| [Appendix](appendix/index) | Technical reference, developer guide |

---

## License

MIT — see the repository **`LICENSE`** file.
