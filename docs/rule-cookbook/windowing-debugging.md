---
title: Windowing and debugging
parent: Rule Cookbook
nav_order: 3
---

# Windowing and debugging

## Rolling average

Rule Lab enriches rows with `temp_rolling_avg` / `degF_rolling_avg` before `evaluate()` (default 1, 5, or 10 minutes by `ts_ms`).

Set `rolling_avg_minutes` in rule config or test API body.

## Window helpers

| Helper | Purpose |
|--------|---------|
| `window_rows_1h(row, rows)` | Samples in trailing 60 minutes |
| `hour_window_ready(window)` | True when window spans ≥ 95% of 1 h |

## Debug print

`print()` inside `evaluate()` appears in Rule Lab event console **on fault hits** (or verbose test mode). Use sparingly in production rules.

## Trace mode

Enable **verbose** on test-rule API to see window spread diagnostics without firing the rule on every row.

## Common false positives

| Symptom | Mitigation |
|---------|------------|
| Warm-up transient | Gate on occupancy or minimum window fill |
| Poll dropout | Require `samples_in_avg` minimum |
| Unit mismatch | Set `temp_unit` in cfg; see `open_fdd.playground.temp_units` |
| Single spike | Rolling avg + consecutive sample recipe |

## Unit conversion

Rules use `row["temp"]` in the rule's configured unit (imperial °F default). MQTT/historian rows include both `degF` and `degC`.
