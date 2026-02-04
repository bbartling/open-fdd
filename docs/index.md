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

1. **[Getting Started](getting_started.md)** — Install, run AHU7 scripts
2. **[Flat Line Sensor Tutorial](flat_line_sensor_tuntorial.md)** — Stuck sensor detection
3. **[Sensor Bounds Tutorial](bounds_sensor_tuntorial.md)** — Out-of-range sensor values
4. **[Configuration](configuration.md)** — Rule types, YAML structure
5. **[API Reference](api_reference.md)** — RuleRunner, reports, brick_resolver
6. **[Data Model & Brick](data_model.md)** — TTL, brick_resolver, external refs

