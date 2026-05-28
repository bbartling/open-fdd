---
title: Home
nav_order: 1
description: "Open-FDD: open_fdd.engine (YAML rules on pandas) and open_fdd.reports (fault summaries and charts). Published as open-fdd on PyPI."
---

# Open-FDD

The **`open-fdd`** PyPI package provides two main modules:

| Module | Role |
|--------|------|
| **`open_fdd.engine`** | Load YAML rules, map columns, run **`RuleRunner`** on a pandas `DataFrame` |
| **`open_fdd.reports`** | Summarize fault episodes, plot flags, optional Word reports |

**`open_fdd.schema`** holds pydantic result types the engine uses; you rarely import it directly.

**Install:** `pip install "open-fdd[engine]"` — adds PyYAML and pydantic. Add **`[reports]`** for matplotlib plots. Bare wheel: `pip install open-fdd` (pandas only).

---

## What it does

- **Loads** rule definitions from YAML (bounds, flatline, hunting, expressions, schedules, weather gates, …).
- **Maps** logical input names to DataFrame columns via **`column_map`** (dict, manifest, or resolver).
- **Runs** checks and returns integer **`*_flag`** columns (`0` / `1`).
- **Reports** (optional) — duration, episodes, charts, `.docx` with **`python-docx`**.

Bring your own CSV or historian export. No database or field bus is required.

**Brick labels in examples are optional.** Cookbook YAML often includes `brick:` on inputs; you can use plain logical names and `column_map={"SAT": "RTU_11_DA_T"}` instead.

---

## Quick start — engine

```bash
pip install "open-fdd[engine]"
```

```python
from open_fdd.engine import RuleRunner

runner = RuleRunner(rules_path="path/to/rules")
df_out = runner.run(df, column_map={"SAT": "supply_air_temp"})
```

---

## Quick start — reports

```python
from open_fdd.reports import get_fault_events, summarize_fault

events = get_fault_events(df_out, flag_col="flatline_flag")
summary = summarize_fault(df_out, flag_col="flatline_flag", timestamp_col="timestamp")
```

---

## Documentation

| Section | Description |
|---------|-------------|
| [Expression rule cookbook](expression_rule_cookbook) | **Primary reference** — expressions, gates, scaling |
| [Engine API](api/engine) | `RuleRunner`, loaders, resolvers |
| [Reports API](api/reports) | Summaries, plots, optional `.docx` |
| [Getting started](getting_started) | Install extras, tests, examples |
| [Rules overview](rules/overview) | Rule types and YAML structure |
| [Column map resolvers](column_map_resolvers) | Manifests and composite maps |
| [How-to guides](howto/index) | PyPI releases, verification, agent shell |
| [Skills and agent shell](howto/skills_and_agent) | `openfdd.toml`, workspace, cron/wake (checkout) |
| [BACnet toolshed](bacnet/index) | `bacnet_toolshed/` CLI on edge hosts |
| [Appendix](appendix/index) | Technical reference, developer guide |

---

## License

MIT — see the repository **`LICENSE`** file.
