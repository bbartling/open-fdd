---
name: timeseries-plots-and-cleaning
description: "Serves plot frame JSON and cleans Grafana-style unit suffixes from feather metrics. Use when building plots pages or preparing data for RuleRunner."
---

# Timeseries plots and cleaning

## Endpoints (legacy)

- `POST /timeseries/query`, `/timeseries/bounds`
- `POST /timeseries/clean-metrics` (preview `commit:false` first)
- `GET /plots/frame`, `/plots/site-frame`, `POST /plots/fdd-frame`

## Verification

Readiness assistant may recommend clean-metrics before plots.

## Reference

See references/REFERENCE.md.
