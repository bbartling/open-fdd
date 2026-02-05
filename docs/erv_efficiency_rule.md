---
title: ERV Efficiency Rule
nav_order: 9
---

# ERV Efficiency Rule

**Type:** `erv_efficiency` — Built-in check; no custom expression.

**Note:** This rule is *custom* — not part of ASHRAE Guideline 36. It was created for open-fdd.

## What the rules engine does

The **erv_efficiency** rule flags when *Energy Recovery Ventilator (ERV) effectiveness* falls outside the expected range. The engine computes effectiveness from OAT entering, OAT leaving the ERV, and return air temp. In heating mode (OAT < oat_low_threshold), effectiveness should be between `erv_efficiency_min_heating` and `erv_efficiency_max_heating`. In cooling mode (OAT > oat_high_threshold), it should be between the cooling min/max. When effectiveness is too low or too high (or OAT–RAT delta is too small to trust the calc), a fault is flagged. AHU with ERV only.

---

## erv_effectiveness_fault (erv_efficiency)

ERV effectiveness outside expected range based on OAT.

```yaml
name: erv_effectiveness_fault
description: ERV effectiveness outside expected range based on OAT
type: erv_efficiency
flag: fc16_flag
equipment_type: [AHU_ERV]

inputs:
  ERV_Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: erv_oat_enter
  ERV_Discharge_Air_Temperature_Sensor:
    brick: Discharge_Air_Temperature_Sensor
    column: erv_oat_leaving
  ERV_Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: erv_eat_enter

params:
  erv_efficiency_min_heating: 0.5
  erv_efficiency_max_heating: 0.9
  erv_efficiency_min_cooling: 0.5
  erv_efficiency_max_cooling: 0.9
  oat_low_threshold: 55.0
  oat_high_threshold: 65.0
  oat_rat_delta_min: 5.0
```

---

**Next:** [Expression Rule Cookbook]({{ "expression_rule_cookbook" | relative_url }})
