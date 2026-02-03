---
title: Home
nav_order: 1
---

# open-fdd

**Config-driven Fault Detection and Diagnostics (FDD)** for HVAC systems. Define fault rules in YAML, run them against pandas DataFrames. Inspired by ASHRAE/NIST guidelines and SkySpark/Axon-style logic.

## What it does

- **YAML rules** — Bounds, flatline, expression, hunting, OA fraction, ERV
- **Pandas-native** — Works directly with DataFrames
- **AHU rules** — FC1–FC16 (duct static, mix temp, PID hunting, economizer, coils)
- **Chiller plant** — Pump differential pressure, CHW flow
- **Sensor checks** — Bad data (bounds) and flatline detection
- **Fault analytics** — Duration, motor runtime, sensor stats
- **BRICK model driven** — Optional: resolve rule inputs from Brick TTL

## Quick run

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
pip install -e ".[dev]"
python examples/ahu7_standalone.py
```

## Docs

1. **[Getting Started](getting_started.md)** — Easiest example, all code inline
2. **[Data Model & Brick](data_model.md)** — TTL from BAS screenshot + CSV, brick_resolver, external refs
3. **[Fault Reports](fault_report.md)** — `summarize_fault`, motor runtime, analytics
4. **[Configuration](configuration.md)** — Rule types, YAML structure
5. **[Examples](examples.md)** — Sensor checks, BRICK-driven, minimal
6. **[API Reference](api_reference.md)** — RuleRunner, reports
