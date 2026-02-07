---
title: Heat Exchanger Effectiveness Rule
nav_order: 7
---

# Heat Exchanger Effectiveness Rule (ERV)

**Type:** `erv_efficiency` — Built-in check; no custom expression.

**Note:** This rule is *custom* — not part of ASHRAE Guideline 36. It was created for open-fdd.

## What the rules engine does

The **erv_efficiency** rule flags when *heat exchanger effectiveness* falls outside the expected range. The engine computes effectiveness from entering and leaving temperatures and the opposing stream temperature. For an ERV (air-to-air): effectiveness = (T_cold_out - T_cold_in) / (T_hot_in - T_cold_in). This same effectiveness formula applies to any counterflow heat exchanger — ERVs, runaround coils, plate heat exchangers, etc. When the cold stream is heated by the hot stream, effectiveness should lie within a band (e.g. 0.5–0.9). Too low indicates fouling, bypass, or airflow issues; too high can indicate sensor error. The open-fdd implementation is wired for ERV (OAT entering/leaving, RAT). Same logic extends to other HX types with appropriate column mapping. AHU with ERV only in current config.

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
