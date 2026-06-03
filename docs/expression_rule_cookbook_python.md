---
title: Expression cookbook (Python / Rule Lab)
parent: Expression rule cookbooks
nav_order: 1
---

# Expression cookbook — Python (Rule Lab)

Production rules live in **`workspace/data/rules_py/*.py`**. Rule Lab saves metadata to `rules_store.json` and source to disk. Batch runner: `POST /api/rules/batch` / `fdd_runner`.

---

## Rule shape

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    """Return False, True, or (True, evidence_rows)."""
    ...
```

| Arg | Meaning |
|-----|---------|
| `row` | Current sample dict (`ts`, `temp`, `value_column`, `value_kind`, …) |
| `cfg` | Thresholds from rule `config` in store (per binding) |
| `rows` | History for windowed logic (flatline/spread) |

**Scripts** (mode `script`): return `out = {"df": dataframe}` from playground — not scheduled as FDD.

---

## Recipe 1 — Flatline 1 hour

Rolling spread of `temp` (or RH via `value_kind`) below tolerance:

```python
from bench_fdd_common import hour_window_ready, window_rows_1h, cfg_threshold, temp_unit_symbol

def evaluate(row, cfg, prev_row=None, rows=None):
    if rows is None:
        return False
    window_rows = window_rows_1h(row, rows)
    if not hour_window_ready(window_rows):
        return False
    tol_key = "flatline_tolerance_rh" if row.get("value_kind") == "rh" else "flatline_tolerance"
    vals = [r.get("temp") for r in window_rows if r.get("temp") is not None]
    if not vals:
        return False
    spread = max(vals) - min(vals)
    if spread < cfg_threshold(cfg, tol_key):
        return True, window_rows
    return False
```

Copy from `rules_py/flatline_1h.py`. Tag rule with a **letter fault code** in Rule Lab (e.g. `VAV-C` for zone temp sensor fault — category `sensor_fault`).

| Cookbook pattern | Typical fault codes | Rule file |
|------------------|---------------------|-----------|
| `flatline_1h` | `VAV-C`, `AHU-C`, `DC-C`, `BLD-B` (OAT) | `flatline_1h.py` |
| `spread_1h` | `VAV-B`, `AHU-A`, `CH-B` | `spread_1h.py`, `duct-t_spread_1h.py` |
| `oob_rolling` | `VAV-C` (bounds), `AHU-D` | `oob_rolling.py` |
| `custom_evaluate` | `AHU-B`, `VAV-A` | site-specific `rules_py` |

Browse the full map: `GET /api/faults/graph` or dashboard **Fault catalog**.

---

## Recipe 2 — Spread / delta 1 hour

Max − min over 1 h above threshold — `spread_1h.py`, `duct-t_spread_1h.py`.

---

## Recipe 3 — Out of bounds (rolling)

`oob_rolling.py` — compare sample to `low` / `high` in `cfg`.

---

## Recipe 4 — Economizer / mixed air (site-specific)

Acme examples: `acme_mixed_air_temp_oob_economizer_diagnostic.py`, `acme_zone_temp_out_of_bounds.py` — bind to model `fdd_input` keys after BACnet import.

---

## Config & bindings

| Item | Where |
|------|--------|
| Thresholds | Rule `config` in UI → passed as `cfg` |
| Point columns | Bindings → feather column names from BRICK `fdd_input` |
| Fault code | Letter suffix only (`VAV-C`, not `VAV-03`); must exist in `GET /api/faults/catalog` |
| Enable | Per-binding flag in `rules_store.json` |

Test: **Lint** → **Test rule** in Rule Lab (`POST /api/playground/test-rule`).

---

## Shared helpers

`bench_fdd_common.py`: `window_rows_1h`, `hour_window_ready`, `cfg_threshold`, `temp_unit_symbol`. Import in site rules; commit shared helpers to git.

Bench seed: `python scripts/setup_bench_afdd.py`.

---

## AI drafting tips

- Start from `flatline_1h.py` or `spread_1h.py`; change thresholds and pick matching `fault_code` from the catalog (same `cookbook_patterns` row).
- Ask AI to explain **spread** and **window length** from test-rule output, not to skip batch run.
- `bench-*` rule ids are excluded from default scheduled batch — use `duct-*` or site prefixes for production timers.

See [Rule Lab storage](howto/rule_lab_storage).
