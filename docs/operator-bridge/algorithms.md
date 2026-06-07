---
title: Algorithms
parent: Operator Bridge
nav_order: 3
---

# Algorithms (coming soon)

The **Algorithms** dashboard tab (`/algorithms`) is a placeholder for **supervisory Python sequences** — the mirror image of Rule Lab FDD:

| | **FDD (Rule Lab)** | **Algorithms (planned)** |
|---|-------------------|--------------------------|
| Purpose | Detect faults | Compute setpoints, request levels, plant enables |
| Entrypoint | `apply_faults_arrow(table, cfg, context)` | `apply_algorithm_arrow(table, cfg, context)` (planned) |
| Output | Boolean fault mask | Numeric outputs / structured dict |
| Historian | Same `feather_store` PyArrow tables | Same |

Until the tab ships, draft patterns live in this doc and in [GL36 algorithm stubs](../rule-cookbook/gl36-algorithm-stubs.md).

## GL36 Trim & Respond reference

Open-FDD algorithms will follow the same ASHRAE Guideline 36 trim & respond methodology already implemented for Niagara in:

**[README_TRIM_RESPOND.md](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md)**

That guide covers:

- VAV zone request generators (cooling + static pressure)
- AHU duct static pressure reset
- AHU supply air temperature reset
- Central plant chiller / boiler enable and HWST / CHWST trim & respond

Porting those blocks to PyArrow is in progress; the dashboard tab shows **COMING SOON** until upload, batch, and BACnet write paths are wired.

## Planned workflow (same kit shape as Rule Lab)

1. Download **algorithm kit** zip from the Algorithms tab (future)
2. Edit **constants** at the top of `algorithm.py` (no `config.json`)
3. Run `python run_test.py` locally against `sample.feather`
4. Upload `algorithm.py` when satisfied

Kit files will match the Rule Lab zip layout (see [Rule Lab — dev kit zip](rule-lab.md#dev-kit-zip-download)).

## Lookback windows

Rules and algorithms that need multi-hour history should use the shared **lookback stats helper** documented in [Lookback window helper](../rule-cookbook/lookback-window.md). Pass `hours=1`, `3`, `6`, `12`, or `24` to print row count, timestamp start/stop, and span for console validation.

Scheduled batch defaults: **1 h** lookback on the FDD loop; **Update all records** in Rule Lab uses **24 h** with 6 h chunks.

## AHU supervisory checks (doc-only stubs)

These are **not** uploaded rules yet — copy-paste references for future algorithm or FDD work.

### Duct static pressure too high

Flags sustained high duct static (possible stuck setpoint, blocked filter, or trim/respond not trimming).

```python
"""AHU duct static high — doc stub (Arrow constants)."""

import pyarrow.compute as pc

VALUE_COLUMN = "duct-static"
HIGH_INWC = 1.20
LOOKBACK_HOURS = 3
MIN_SAMPLES_ABOVE = 6


def _kit_lookback_stats(table, *, hours=None):
    h = hours if hours is not None else LOOKBACK_HOURS
    ts = pc.cast(table["timestamp"], "timestamp[us, UTC]")
    tmin = pc.min(ts).as_py()
    tmax = pc.max(ts).as_py()
    span_h = (tmax - tmin).total_seconds() / 3600.0 if tmin and tmax else 0.0
    print(f"lookback={h}h rows={table.num_rows} start={tmin} stop={tmax} span={span_h:.2f}h")


def apply_faults_arrow(table, cfg, context=None):
    _kit_lookback_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    high = pc.greater(vals, HIGH_INWC)
    # Require several consecutive highs (~30 min at 5 min poll)
    from open_fdd.arrow_runtime.windows import arrow_consecutive_true

    streak = arrow_consecutive_true(high, MIN_SAMPLES_ABOVE)
    return streak
```

### Supply air temperature too cold (cooling coil over-delivering)

```python
"""AHU SAT too cold vs setpoint — doc stub."""

import pyarrow.compute as pc

SAT_COLUMN = "sa-t"
SP_COLUMN = "sa-t-sp"
COLD_DELTA_F = 5.0
LOOKBACK_HOURS = 1


def _kit_lookback_stats(table, *, hours=None):
    h = hours if hours is not None else LOOKBACK_HOURS
    ts = pc.cast(table["timestamp"], "timestamp[us, UTC]")
    tmin = pc.min(ts).as_py()
    tmax = pc.max(ts).as_py()
    span_h = (tmax - tmin).total_seconds() / 3600.0 if tmin and tmax else 0.0
    print(f"lookback={h}h rows={table.num_rows} start={tmin} stop={tmax} span={span_h:.2f}h")


def apply_faults_arrow(table, cfg, context=None):
    _kit_lookback_stats(table)
    sat = pc.cast(table[SAT_COLUMN], "float64")
    sp = pc.cast(table[SP_COLUMN], "float64")
    return pc.less(pc.subtract(sat, sp), -COLD_DELTA_F)
```

## Plant supervisory checks (doc-only)

See [GL36 algorithm stubs](../rule-cookbook/gl36-algorithm-stubs.md) for chiller plant enable, HWST trim & respond, and CHW DP/CHWST reset patterns aligned with the Niagara README.

## Related

- [Rule Lab](rule-lab.md) — live FDD authoring
- [Model workflow](model-workflow.md) — point bindings
- [Windowing & debugging](../rule-cookbook/windowing-debugging.md) — rolling windows
