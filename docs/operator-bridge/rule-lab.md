---
title: Rule Lab
parent: Operator Bridge
nav_order: 2
---

# Rule Lab

Rule Lab authors **Arrow-native** Python FDD rules against the feather historian.

## Equipment-scoped test and export

Use **Equipment-scoped test & export** on Rule Lab:

1. Select site, equipment, and sensor (point).
2. **Test selected rule** or **Test all for equipment** against recent feather data.
3. **Download equipment kit** — zip with `manifest.json`, `equipment.json`, `points.json`, per-rule samples, expanded helper source, and commissioning export subset.

API: `GET /api/rules/export-equipment-kit?equipment_id=…` · expanded helpers: `GET /api/playground/rules/{id}/source-expanded`.

## Export all rules

Integrators can download **Export all rules** — one zip with per-rule kits, `manifest.json`,
catalog snapshots, and model TTL. API: `GET /api/rules/export-all-kit`. Bench rules use **module constants** at the top of `rule.py` — no browser config panel, no `config.json` in the dev kit zip.

```python
"""Bench OA-T out of bounds (Arrow)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-t"
OAT_LOW = 68.0
OAT_HIGH = 88.0
LOOKBACK_HOURS = 1


def _kit_lookback_stats(table, *, hours=None):
    h = hours if hours is not None else LOOKBACK_HOURS
    ts = pc.cast(table["timestamp"], "timestamp[us, UTC]")
    tmin = pc.min(ts).as_py()
    tmax = pc.max(ts).as_py()
    span_h = (tmax - tmin).total_seconds() / 3600.0 if tmin and tmax else 0.0
    print(f"lookback={h}h rows={table.num_rows} start={tmin} stop={tmax} span={span_h:.2f}h")


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(
        f"column={VALUE_COLUMN} min={pc.min(vals).as_py():.2f} "
        f"max={pc.max(vals).as_py():.2f} mean={pc.mean(vals).as_py():.2f}"
    )


def apply_faults_arrow(table, cfg, context=None):
    _kit_lookback_stats(table)
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.or_(pc.less(vals, OAT_LOW), pc.greater(vals, OAT_HIGH))
```

## Workflow

1. **Download kit** — PyArrow zip (see below)
2. **Edit constants** locally (`VALUE_COLUMN`, limits, `LOOKBACK_HOURS`, `WINDOW_SAMPLES`)
3. **Run** `pip install -r requirements.txt` then `python run_test.py`
4. **Upload** `rule.py` on Rule Lab (integrator)

Upload validation (Phase B): AST parse, forbidden imports (**no pandas/numpy**), `apply_faults_arrow(table, cfg, context=None)` signature for fault rules. Script-mode rules must use **`table`** (PyArrow), not legacy **`df`** DataFrames — lint errors explain this for AI agents.

The bridge runs rules on **PyArrow tables** via `open_fdd.arrow_runtime`, and persists `.py` sources under `workspace/data/rules_py/`.

- **Quick test** — `POST /api/playground/test-rule` (default 3 h lookback)
- **Batch** — `POST /api/rules/batch` / `openfdd-fdd-loop` timer (**1 h** default lookback)
- **Update all records** — 24 h lookback, 6 h chunks (`use_chunks: true`)
- **Templates** — `GET /api/playground/arrow-templates`

Pin points to rules via **Model & assignments** (`/model`) commissioning JSON or BACnet tree right-click. Export shows Rule Lab **names** on each point (`fdd_rules_linked`); import uses rule **ids** (`fdd_rule_ids`).

Bench seed: `python3 scripts/setup_bench_afdd.py` — imports `bench_import_model.json` and bench cookbook rules with matching id/name pairs.

## Dev kit zip (download)

**Download kit** on Rule Lab exports `openfdd-rule-kit-<rule_id>.zip` with:

| File | Purpose |
|------|---------|
| `rule.py` | Arrow rule + **constants** at top; optional `_kit_lookback_stats` / `_kit_value_stats` helpers |
| `data.py` | `SITE_ID`, `LOOKBACK_HOURS`, `load_table()` reading `sample.feather` |
| `sample.feather` | Full historian window for the kit lookback (all rows, not a CSV preview) |
| `run_test.py` | Runs `rule.apply_faults_arrow(table, {}, context=...)` and prints `flagged=N` |
| `requirements.txt` | `open-fdd>=3.0.1` and `pyarrow` |
| `README.md` | Install and run instructions |
| `column_map.json` | BRICK logical keys → feather column names |
| `kit_meta.json` | Export metadata (site, columns, row count, lookback hours) |

**Not included:** `config.json` (retired — tune thresholds as Python constants).

Local test:

```bash
unzip openfdd-rule-kit-*.zip
cd openfdd-rule-kit-*
pip install -r requirements.txt
python run_test.py
```

Expected console output:

```
site=demo lookback_h=3 rows=…
lookback=3h rows=… start=… stop=… span=2.98h
column=oa-t min=… max=… mean=…
flagged=…
```

## Lookback windows

Rules that need multi-hour history should call `_kit_lookback_stats(table)` (see [Lookback window helper]({{ "/rule-cookbook/lookback-window/" | relative_url }})). Pass `hours=1`, `3`, `6`, `12`, or `24` to validate timestamp span in the console.

Rolling-window rules (flatline, spread) use `WINDOW_SAMPLES` (~12 samples ≈ 1 h at 5 min poll) — see [Windowing & debugging]({{ "/rule-cookbook/windowing-debugging/" | relative_url }}).

## Algorithms (supervisory — coming soon)

GL36 trim & respond and plant reset sequences will live on the **[Algorithms]({{ "/operator-bridge/algorithms/" | relative_url }})** tab with the same zip kit shape but `apply_algorithm_arrow` outputs. Reference: [README_TRIM_RESPOND](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md).

## Related

- [Model workflow]({{ "/operator-bridge/model-workflow/" | relative_url }})
- [Arrow recipes]({{ "/rule-cookbook/arrow-recipes/" | relative_url }})
- [GL36 algorithm stubs]({{ "/rule-cookbook/gl36-algorithm-stubs/" | relative_url }}) (doc-only)
