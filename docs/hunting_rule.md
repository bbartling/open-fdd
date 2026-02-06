---
title: Hunting Rule
nav_order: 7
---

# Hunting Rule

**Type:** `hunting` — Built-in check; no custom expression.

## What the rules engine does

The **hunting** rule flags which is defined by ASHRAE Guideline 36 Fault Rule Four is *excessive operating state changes* — when the AHU cycles too rapidly between heating, economizer, and mechanical cooling modes. This is often caused by PID tuning issues (hunting). The engine builds an operating-state vector from economizer damper, supply fan VFD, heating valve, and cooling valve. It counts how many state changes occur in a rolling `window`. When the sum exceeds `delta_os_max`, a fault is flagged.

---

## excessive_ahu_state_changes (hunting)

Excessive AHU operating state changes (PID hunting).

```yaml
name: excessive_ahu_state_changes
description: Excessive AHU operating state changes detected (hunting behavior)
type: hunting
flag: fc4_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed
  Heating_Valve_Command:
    brick: Valve_Command
    column: heating_sig
  Cooling_Valve_Command:
    brick: Valve_Command
    column: cooling_sig

params:
  delta_os_max: 10
  ahu_min_oa_dpr: 0.1
  window: 60
```

---

**Next:** [OA Fraction Rule]({{ "oa_fraction_rule" | relative_url }})
