---
title: Grade-A FDD changelog (3.0.18)
nav_exclude: true
---

# Grade-A FDD — 3.0.18 foundation

## Added

- **Gap audit:** `docs/development/fdd_grade_a_gap_audit.md`
- **Canonical fault schema:** `open_fdd/faults/schema.py`
- **YAML catalog (starter, 19 faults):** `open_fdd/faults/catalog/*.yaml` — DATA, CTRL, BACNET, AHU, CHW, VAV, RTU, CRS
- **Catalog loader:** `open_fdd/faults/catalog.py` with legacy letter aliases (`AHU-E` → `AHU-ECON-001`)
- **Arrow primitives:** `open_fdd/arrow_runtime/primitives.py`
- **Evidence builder:** `open_fdd/arrow_runtime/evidence.py`
- **Portfolio interval schema:** `portfolio/store/interval_schema.py` + `TuningProposal`
- **Tests:** catalog validation, primitives, no-pandas edge guard

## Naming convention (new)

| Old | New example |
|-----|-------------|
| `AHU-E` | `AHU-ECON-001` (`ahu.economizer.not_using_free_cooling`) |
| `AHU-B` | `AHU-SHC-001` |
| `BLD-D` | `DATA-STAL-001` |
| `CH-B` | `CHW-DT-001` |

Letter codes remain **aliases** until bridge `fault_catalog.py` sync (planned 3.0.19).

## Remaining (future patches)

- Rule templates per system (`open_fdd/faults/templates/`)
- Full family YAML (VAV, RTU, DOAS, FCU, CTW, BLR, CRS, ERV)
- Bridge API reads `open_fdd.faults.catalog_export()`
- Portfolio interval ingest (JSONL/Parquet) + Dash operator cards
- AI tuning proposal workflow + `docs/portfolio/ai-agent-tuning.md`
- Pandas removal from `fdd_runner` arrow path
- Docs pages: central-plants, healthcare, G36, ASHRAE 207 economizer

## How to run tests

```bash
python3 -m pytest open_fdd/tests/faults open_fdd/tests/arrow_runtime/test_primitives.py tests/test_no_pandas_edge_fdd.py -q
```

## Portfolio (unchanged from 3.0.17)

```bash
source infra/ansible/secrets/acme.env.local
python3 scripts/portfolio_collect.py
.venv/bin/python portfolio/dash/app.py
# http://127.0.0.1:8050
```
