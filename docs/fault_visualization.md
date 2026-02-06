---
title: Fault Visualization & Zooming
nav_order: 12
---

# Fault Visualization & Zooming

After running Brick-driven fault detection, you get fault flags (e.g. `fc1_flag`, `fc2_flag`, …). The next step is **zooming in on fault events** to inspect what the signals looked like when the rule fired. This sets up the follow-on tutorial: **working with false positives**.

## Why zoom?

Fault flags are boolean time series. A contiguous run of `True` is a **fault event**. To understand whether a flag is a true fault or a false positive, you need to:

1. **Extract events** — contiguous regions where the flag is True
2. **Zoom in** — plot the time window around each event with the relevant signals
3. **Inspect** — look at SAT, MAT, OAT, damper, valves, duct static, etc. during the fault window

## Install Jupyter / IPython

To run the notebook, install Jupyter (includes IPython):

```bash
pip install jupyter
# or with open-fdd extras:
pip install "open-fdd[dev]"
```

Then launch Jupyter:

```bash
jupyter notebook
```

---

## IPython notebook

The notebook does exactly that. **View online:** [run_and_viz_faults.ipynb](https://github.com/bbartling/open-fdd/blob/master/examples/brick_fault_viz/run_and_viz_faults.ipynb)

1. **Runs the Brick workflow** — same as `run_all_rules_brick.py` (TTL → column map → rules → CSV)
2. **Extracts fault events** — contiguous runs of True per flag column
3. **Randomly samples events** — picks N events and plots a zoomed window around each
4. **Shows signals + fault shading** — SAT, MAT, OAT, RAT, duct static, fan speed, damper, valves

### Quick start

```bash
# From project root
jupyter notebook examples/brick_fault_viz/run_and_viz_faults.ipynb
```

Run all cells. You’ll see:

- Fault sample counts per flag (fc1, fc2, fc3, fc4, bad_sensor, flatline)
- Total fault events (contiguous regions)
- **Random zoom plots** — 3 randomly chosen events with signals and fault region shaded

### Event extraction

An *event* is a contiguous run of `True` in a flag column:

```python
def get_fault_events(df, flag_col):
    """Return (start_iloc, end_iloc, flag_name) for each contiguous fault region."""
    s = df[flag_col].astype(bool)
    if not s.any():
        return []
    groups = (~s).cumsum()
    fault_groups = groups[s]
    events = []
    for g in fault_groups.unique():
        idx = fault_groups[fault_groups == g].index
        pos = df.index.get_indexer(idx)
        events.append((int(pos.min()), int(pos.max()), flag_col))
    return events
```

### Random zoom

```python
import numpy as np

rng = np.random.default_rng(42)
n_sample = 3
sampled = rng.choice(events, size=min(n_sample, len(events)), replace=False)

for event in sampled:
    zoom_on_event(result, event, pad=48, signal_cols=plot_cols)
    plt.show()
```

`pad=48` means 48 samples before and after the event center (e.g. 48 × 15 min ≈ 12 hours each side for 15‑min data).

## Next: False positives

Many fault flags are **false positives** — the rule fired but the condition was acceptable:

- **Startup / shutdown** — equipment ramping up or down
- **Setpoint change** — operator or schedule adjustment
- **Sensor noise** — brief spikes or dropouts
- **Edge cases** — rule logic doesn’t account for a valid operating mode

The next tutorial will cover:

- Filtering by occupancy / schedule
- Rolling-window confirmation (require N consecutive samples)
- Manual review workflows
- Tuning thresholds to reduce false positives

---

**See also:** [Data Model & Brick]({{ "data_model" | relative_url }}) — validate and run the Brick workflow before visualizing.

**Next:** [Configuration]({{ "configuration" | relative_url }}) — rule types, YAML structure
