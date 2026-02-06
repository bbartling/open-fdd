---
title: Home
nav_order: 1
---

# open-fdd

**Config-driven Fault Detection and Diagnostics (FDD)** for HVAC systems. Define fault rules in YAML, run them against pandas DataFrames. Inspired by ASHRAE/NIST guidelines and SkySpark/Axon-style logic.

## What it does

A **rules engine** is software that runs automated checks on your data — when a condition is met (e.g., duct static too low, sensor stuck), it flags a fault. For mechanical engineers and facility managers, that means less manual digging through BAS trends and faster detection of HVAC problems. open-fdd is a rules engine built on **pandas**, the free, open-source Python library for tabular data. A **DataFrame** is a table of rows and columns (like a spreadsheet) — pandas DataFrames give you fast, vectorized math ideal for time-series sensor data from your building. Define fault rules in YAML (bounds, flatline, custom expressions, hunting, OA fraction, ERV), run them against your DataFrame, and get boolean fault flags. Optional BRICK model support lets you map rule inputs from a semantic building model. The **Fault Rule Cookbook** offers ready-made recipes online; pick what you need and copy into your project.

**AI-friendly:** Python and pandas are staples of modern data science — most projects use them in some form. In the age of AI, open-fdd fits easily with your existing AI tooling. Use your preferred AI assistant to translate expensive proprietary FDD equations into Python, pandas, and NumPy — easy peasy.

**Smart buildings & IoT:** Coupled with modern smart-building IoT data modeling efforts (e.g., BRICK), this could be a powerful solution. Pandas is used widely across many domains and scales to massive datasets — it just needs to be tailored to smart-building fault detection and diagnostics. The FDD industry is notoriously proprietary and expensive. A free, open-source option that executes FDD effectively has been missing, but it can be.

All fault rules in **open-fdd** with full YAML. Copy from the browser into your project — create a folder like `my_rules` on your desktop, save each rule as a `.yaml` file, and run the tutorial from there. Rules also live in [`open_fdd/rules/`](https://github.com/bbartling/open-fdd/tree/master/open_fdd/rules).

**Rule types:** `bounds` · `flatline` · `expression` · `hunting` · `oa_fraction` · `erv_efficiency` — All produce boolean (true/false) fault flags, but only `expression` lets you write custom logic; the others use built-in checks. See [Bounds]({{ "bounds_rule" | relative_url }}), [Flatline]({{ "flatline_rule" | relative_url }}), [Hunting]({{ "hunting_rule" | relative_url }}), [OA Fraction]({{ "oa_fraction_rule" | relative_url }}), [ERV Efficiency]({{ "erv_efficiency_rule" | relative_url }}) for those rule types.

## Docs

1. **[Getting Started]({{ "getting_started" | relative_url }})** — Install, run AHU7 scripts
2. **[Bounds Rule]({{ "bounds_rule" | relative_url }})** — Sensor out-of-range (built-in)
3. **[Flatline Rule]({{ "flatline_rule" | relative_url }})** — Stuck sensor detection (built-in)
4. **[Hunting Rule]({{ "hunting_rule" | relative_url }})** — Excessive AHU state changes (built-in)
5. **[OA Fraction Rule]({{ "oa_fraction_rule" | relative_url }})** — OA fraction calc error (built-in)
6. **[ERV Efficiency Rule]({{ "erv_efficiency_rule" | relative_url }})** — ERV effectiveness (built-in, custom)
7. **[Expression Rule Cookbook]({{ "expression_rule_cookbook" | relative_url }})** — Custom expression rules (AHU, chiller, weather)
8. **[Flat Line Sensor Tutorial]({{ "flat_line_sensor_tuntorial" | relative_url }})** — Stuck sensor detection
9. **[Sensor Bounds Tutorial]({{ "bounds_sensor_tuntorial" | relative_url }})** — Out-of-range sensor values
10. **[SPARQL & Validate Prereq]({{ "sparql_validate_prereq" | relative_url }})** — Test SPARQL, validate model before faults
11. **[Data Model & Brick]({{ "data_model" | relative_url }})** — Run faults, Brick TTL, column map
12. **[Fault Visualization & Zooming]({{ "fault_visualization" | relative_url }})** — Zoom in on fault events, IPython notebook
13. **[AI-Assisted FDD Roadmap]({{ "ai_assisted_fdd_roadmap" | relative_url }})** — Agentic workflows, false positive tuning, root cause analysis
14. **[Configuration]({{ "configuration" | relative_url }})** — Rule types, YAML structure
15. **[API Reference]({{ "api_reference" | relative_url }})** — RuleRunner, reports, brick_resolver, Brick workflow

