---
title: Developer guide
parent: Appendix
nav_order: 2
---

# Developer guide (engine repository)

This repo is the **`open-fdd`** PyPI package: YAML rules + pandas. There is **no** FastAPI app or Docker Compose here—that lives in **[open-fdd-afdd-stack](https://github.com/bbartling/open-fdd-afdd-stack)** ([stack docs](https://bbartling.github.io/open-fdd-afdd-stack/)).

## Layout

| Path | Role |
|------|------|
| `open_fdd/engine/` | `RuleRunner`, rule loading, expression eval, **`column_map_resolver`**, Brick helpers |
| `open_fdd/schema/`, `open_fdd/reports/` | Shared models / reporting helpers |
| `openfdd_engine/` | Thin re-export namespace in the clone (optional **`openfdd-engine`** on PyPI) |
| `packages/openfdd-engine/` | Build metadata for the shim package |
| `open_fdd/tests/` | Pytest suites (`engine`, schema, etc.) |
| `examples/` | Notebooks, workshops, resolver demos |

## Tests

```bash
pip install -e ".[dev]"
pytest open_fdd/tests/ -v --tb=short
```

Details: [TESTING.md](https://github.com/bbartling/open-fdd/blob/master/TESTING.md).

## Extending the engine

- New rule types or runner behavior → `open_fdd/engine/` (keep YAML schema stable where possible).
- Public API surface → export from `open_fdd/engine/__init__.py` and document on this site ([Getting started](../getting_started), [Column map & resolvers](../column_map_resolvers)).

## Platform (API, React, SQL, Grafana, BACnet)

Use the stack **[Developer guide](https://bbartling.github.io/open-fdd-afdd-stack/appendix/developer_guide)** and **[Technical reference](https://bbartling.github.io/open-fdd-afdd-stack/appendix/technical_reference)** for migrations under `stack/sql/`, the React app, WebSockets, and operations.
