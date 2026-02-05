---
title: OA Fraction Rule
nav_order: 8
---

# OA Fraction Rule

**Type:** `oa_fraction` — Built-in check; no custom expression.

## What the rules engine does

The **oa_fraction** rule flags when the *calculated outdoor air (OA) fraction* deviates too much from the *minimum design OA fraction* in non-economizer modes. The engine computes OA fraction from MAT, RAT, and OAT using the standard enthalpy/temperature-based formula. It compares that to the design minimum (based on `ahu_min_oa_cfm_design` and supply airflow). When `|OA_frac_calc - OA_min| > airflow_err_thres` and the AHU is in heating (OS1) or mechanical-only cooling (OS4), a fault is flagged. Catches OA fraction calculation errors or AHU not maintaining design airflow. ASHRAE Guideline 36 Fault Rule Six.

---

## oa_fraction_airflow_error (oa_fraction)

OA fraction calc error or AHU not maintaining design airflow.

```yaml
name: oa_fraction_airflow_error
description: OA fraction calc error or AHU not maintaining design airflow in non-economizer modes
type: oa_fraction
flag: fc6_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  supply_fan_air_volume:
    brick: Supply_Fan_Air_Flow_Sensor
    column: supply_fan_air_volume
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  rat:
    brick: Return_Air_Temperature_Sensor
    column: rat
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig

params:
  airflow_err_thres: 0.1
  ahu_min_oa_cfm_design: 1000.0
  oat_rat_delta_min: 5.0
  ahu_min_oa_dpr: 0.1
```

---

**Next:** [ERV Efficiency Rule]({{ "erv_efficiency_rule" | relative_url }})
