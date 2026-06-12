---
title: Lookback window helper
parent: Rule Cookbook
nav_order: 3
---

# Lookback window helper

Rules that depend on **time history** (flatline, spread, streaks, trim/respond validation) should print a clear window summary in the Rule Lab console or local `run_test.py` output.

## Recommended pattern (copy into `rule.py`)

Use module constants for the lookback you intend; the bridge passes the full feather window into `apply_faults_arrow` based on batch `lookback_hours` (default **1 h** on the scheduled loop; **24 h** when using **Update all records** with chunks).

```python
import pyarrow.compute as pc

LOOKBACK_HOURS = 3  # tune: 1, 3, 6, 12, 24


def _kit_lookback_stats(table, *, hours=None):
    """Dev helper — prints row count, timestamp span, and configured lookback."""
    h = hours if hours is not None else LOOKBACK_HOURS
    if "timestamp" not in table.column_names:
        print(f"lookback={h}h rows={table.num_rows} (no timestamp column)")
        return
    ts = pc.cast(table["timestamp"], "timestamp[us, UTC]")
    tmin = pc.min(ts).as_py()
    tmax = pc.max(ts).as_py()
    if tmin is None or tmax is None:
        print(f"lookback={h}h rows={table.num_rows} start=None stop=None span=0.00h")
        return
    span_h = (tmax - tmin).total_seconds() / 3600.0
    print(
        f"lookback={h}h rows={table.num_rows} "
        f"start={tmin.isoformat()} stop={tmax.isoformat()} span={span_h:.2f}h"
    )


def _kit_value_stats(table, column):
    vals = pc.cast(table[column], "float64")
    print(
        f"column={column} min={pc.min(vals).as_py():.2f} "
        f"max={pc.max(vals).as_py():.2f} mean={pc.mean(vals).as_py():.2f}"
    )


def apply_faults_arrow(table, cfg, context=None):
    _kit_lookback_stats(table)
    _kit_value_stats(table, "oa-t")
    # ... fault logic ...
```

## Why not hide this behind a library call yet?

A future `open_fdd.arrow_runtime.kit.lookback_stats(table, hours=3)` helper is reasonable once the Algorithms tab shares the same kit export path. For now, keeping the helper **inline in `rule.py`** matches the constants-first Rule Lab style and prints the same fields in:

- Local `run_test.py`
- Rule Lab **Quick test** console
- Batch run logs

## Lookback vs rolling samples

| Concept | Controlled by | Typical use |
|---------|---------------|-------------|
| **Historian lookback** | Batch `lookback_hours`, FDD loop env | How many rows are in `table` |
| **Rolling window** | `WINDOW_SAMPLES` constant (~12 ≈ 1 h @ 5 min poll) | Flatline, spread, consecutive-true |

Always call `_kit_lookback_stats(table)` first so operators can confirm the table span matches expectations before interpreting rolling-window faults.

## Batch intervals

| Trigger | Default lookback |
|---------|------------------|
| `openfdd-fdd-loop` / `OFDD_FDD_INTERVAL_MINUTES` | 1 h |
| Rule Lab **Update all records** | 24 h (`chunk_hours: 6`, `use_chunks: true`) |
| Rule Lab Quick test | 3 h (UI default) |

See [Windowing & debugging]({{ "/rule-cookbook/windowing-debugging/" | relative_url }}) for `arrow_rolling_min` / `arrow_consecutive_true`.
