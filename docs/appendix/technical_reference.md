---
title: Technical reference
parent: Appendix
nav_order: 1
nav_exclude: true
---

# Technical reference

Maintainer-focused layout for the **`open-fdd`** PyPI package (rules engine on pandas).

**Setup:** `python3 -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`). Install: `pip install -e ".[dev]"`. Tests: `pytest`.

---

## Directory structure

```
open-fdd/
├── open_fdd/
│   ├── engine/           # RuleRunner, checks, column_map resolvers, rule YAML schema
│   ├── schema/         # FDD result / event models (pydantic)
│   ├── reports/        # Optional: fault_viz, docx, fault_report (extra deps may apply)
│   └── tests/          # pytest suite (engine + schema)
├── docs/               # Jekyll / Just the Docs site
├── examples/           # Runnable examples and notebooks
├── packages/
│   └── openfdd-engine/ # Optional thin PyPI wrapper (separate distribution)
├── scripts/            # build_docs_pdf.py (optional doc bundle)
├── tools/              # Optional maintainer scripts
└── pyproject.toml
```

---

## Tests

| Path | Role |
|------|------|
| `open_fdd/tests/engine/` | `RuleRunner`, expressions, schedules, column maps |
| `open_fdd/tests/test_schema.py` | Result / event schema |
| `open_fdd/tests/examples/` | Import smoke tests |

CI runs `pytest` from the repo root after `pip install -e ".[dev]"`.

---

## Related reading

- [Column map resolvers](../column_map_resolvers)
- [Expression rule cookbook](../expression_rule_cookbook)
- [Rules overview](../rules/overview)
- [API — Engine](../api/engine)
