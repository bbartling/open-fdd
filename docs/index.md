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


## Docs

1. **[Getting Started](getting_started.md)** — AHU7 tutorial: run the script, then Brick data model
2. **[Configuration](configuration.md)** — Rule types, YAML structure
3. **[API Reference](api_reference.md)** — RuleRunner, reports, brick_resolver
4. **[Examples](examples.md)** — API examples: minimal, manual map, Brick map, analytics
5. **[Data Model & Brick](data_model.md)** — TTL, brick_resolver, external refs
6. **[Fault Reports](fault_report.md)** — `summarize_fault`, motor runtime
