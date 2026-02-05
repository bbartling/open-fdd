---
title: Home
nav_order: 1
---

# open-fdd

**Config-driven Fault Detection and Diagnostics (FDD)** for HVAC systems. Define fault rules in YAML, run them against pandas DataFrames. Inspired by ASHRAE/NIST guidelines and SkySpark/Axon-style logic.

## What it does

- **YAML rules** — Bounds, flatline, expression, hunting, OA fraction, ERV
- **Pandas-native** — Works directly with DataFrames
- **Sensor checks** — Bad data (bounds) and flatline detection
- **Fault analytics** — Duration, motor runtime, sensor stats
- **BRICK model driven** — Optional: resolve rule inputs from Brick TTL
- **Fault Rule Cookbook** — Fault rule recipes available online; pick and choose what you need and copy locally into your project

## Docs

1. **[Getting Started]({{ "getting_started" | relative_url }})** — Install, run AHU7 scripts
2. **[Flat Line Sensor Tutorial]({{ "flat_line_sensor_tuntorial" | relative_url }})** — Stuck sensor detection
3. **[Sensor Bounds Tutorial]({{ "bounds_sensor_tuntorial" | relative_url }})** — Out-of-range sensor values
4. **[Expression Rule Cookbook]({{ "expression_rule_cookbook" | relative_url }})** — All rules (AHU, chiller, weather)
5. **[Configuration]({{ "configuration" | relative_url }})** — Rule types, YAML structure
6. **[API Reference]({{ "api_reference" | relative_url }})** — RuleRunner, reports, brick_resolver
7. **[Data Model & Brick]({{ "data_model" | relative_url }})** — TTL, brick_resolver, external refs

