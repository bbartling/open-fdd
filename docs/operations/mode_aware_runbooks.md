---
title: Mode-aware runbooks
parent: Operations
nav_order: 6
---

# Mode-aware runbooks

This repository is the **`open_fdd`** **rules engine** only. There is no **`--mode collector|model|engine|full`** Docker orchestration in-tree.

---

## Recommended checks

| Goal | Command |
|------|---------|
| Verify install | `python -c "import open_fdd; print('ok')"` |
| Run unit tests | `pytest` |
| Editable dev install | `pip install -e ".[dev]"` |

---

## Test bench vs production data

Treat **synthetic** or **lab** CSVs as a different **operational state** from **production** BMS exports: tighten tolerances, window sizes, and alert routing in production. See [Operational states](../concepts/operational_states).
