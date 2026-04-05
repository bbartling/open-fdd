---
title: Examples (repository)
nav_order: 4
---

# Examples in the `open-fdd` repository

All paths are under **[github.com/bbartling/open-fdd/tree/master/examples](https://github.com/bbartling/open-fdd/tree/master/examples)**. They are meant to be opened locally after `git clone` (notebooks, CSVs, small Python demos).

| Area | What it shows |
|------|----------------|
| **`column_map_resolver_workshop/`** | `ManifestColumnMapResolver`, composite resolvers, `RuleRunner` with your own column names |
| **`AHU/`**, **`my_rules/`** | YAML rules + pandas workflows, workshops |
| **`223P_engineering/`** | Engineering metadata and analytics *next to* fault outputs |
| **`column_map_manifests/`** | Sample manifest YAML/JSON for `column_map` |

**Docker / BACnet / API** examples and `bootstrap.sh` flows live with the platform: **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)**.

Install only what you need:

```bash
pip install "open-fdd[brick,viz,dev]"   # notebooks + Brick helpers
```
