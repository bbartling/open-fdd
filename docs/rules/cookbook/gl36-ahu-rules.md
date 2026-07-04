---
title: GL36 AHU rules
parent: Rule Cookbook
nav_order: 5
---

# GL36-inspired AHU rules (A–M)

Patterns adapted from **ASHRAE Guideline 36** AFDD guidance. Thresholds are tunable — adjust SQL literals or Pandas params per site.

| Rule | Summary | Code | SQL cookbook |
|------|---------|------|--------------|
| A | Duct static below SP at high fan | **AHU-A** | [§4](datafusion-sql-cookbook.html#4-duct-static-low-at-full-fan-gl36-rule-a) |
| B | MAT below OAT/RAT envelope | **AHU-D** | [§5](datafusion-sql-cookbook.html#5-mixed-air-below-oatr-envelope-gl36-rule-b) |
| C | MAT above OAT/RAT envelope | **AHU-D** | [§6](datafusion-sql-cookbook.html#6-mixed-air-above-oatr-envelope-gl36-rule-c) |
| D | SAT cold when heating commanded | **AHU-B** | [§7](datafusion-sql-cookbook.html#7-discharge-cold-when-heating-commanded-gl36-rule-d) |
| E | SAT low with full heating | **AHU-C** | [§8](datafusion-sql-cookbook.html#8-sat-low-with-full-heating-gl36-rule-e) |
| F | SAT/MAT mismatch in economizer | **AHU-E** | Extend SQL from Rules B–C + damper/cool gates |
| G | OAT too warm for free cooling | **AHU-E** | OAT vs SAT SP + econ open |
| H | OAT/MAT mismatch + mech cool | **AHU-E** | \|MAT−OAT\| + cool + damper |
| I | OAT/MAT mismatch econ only | **AHU-E** | \|MAT−OAT\| + high damper |
| J | SAT above blend in cooling | **AHU-B** | SAT vs MAT + cool mode |
| K | SAT above SP full cooling | **AHU-C** | SAT vs SP + cool > 90% |
| L | CHW ΔT when coils off | **CH-C** | Return − supply when valve closed |
| M | HW ΔT when coils off | **AHU-B** | HW rise when heat valve closed |

## Pandas equivalents

Rules A–E and mixing envelope: [Pandas cookbook §3–4](pandas-cookbook.html).

## Binding to fault catalog

1. Pick a letter code (or site-specific ID like `AHU-ECON-001`).
2. Set **fault_code** on the rule in SQL FDD workbench.
3. Confirmed faults aggregate to `GET /api/faults/status`.

## Economizer starters

Combine:

- `oa_damper_pct`, `clg_valve_pct`, `fan_cmd`
- OAT vs SAT setpoint for free-cooling eligibility

See [Economizer stuck closed](datafusion-sql-cookbook.html#10-economizer-stuck-closed) in the SQL cookbook.
