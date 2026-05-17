---
title: API Reference
nav_order: 6
has_children: true
---

# API reference

The **`open-fdd`** wheel exposes a **Python API** only (no bundled HTTP server).

| Module | Documentation |
|--------|----------------|
| **`open_fdd.engine`** | [Engine API](engine) — `RuleRunner`, YAML rules, `column_map` |
| **`open_fdd.reports`** | [Reports API](reports) — summaries, plots, optional `.docx` |

**`open_fdd.schema`** defines fault result/event models used internally by the engine; import from there only if you need typed rows for storage or export.

**Extras:** `pip install "open-fdd[engine]"` · `pip install "open-fdd[reports]"` · `pip install python-docx` for Word output.
