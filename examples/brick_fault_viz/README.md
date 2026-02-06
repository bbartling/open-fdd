# Brick Fault Visualization

Run Brick-driven fault detection and **zoom in on fault events** in an IPython notebook.

## Quick start

1. From project root: `jupyter notebook examples/brick_fault_viz/run_and_viz_faults.ipynb`
2. Run all cells
3. Inspect the random fault-event zooms

## What it does

- Runs the same Brick workflow as `run_all_rules_brick.py` (TTL → column map → rules → CSV)
- Extracts **fault events** (contiguous runs of True in each flag column)
- **Randomly samples** events and plots a zoomed time window around each
- Shows signals (SAT, MAT, OAT, RAT, duct static, damper, valves) with fault region shaded

## Next tutorial

**Working with false positives** — many fault flags are false positives (startup, setpoint change, sensor noise). The next notebook will cover filtering by occupancy, rolling-window confirmation, and tuning thresholds.
