---
title: RTU faults
parent: Fault Codes
nav_order: 4
---

# RTU faults

Packaged rooftop unit codes (sample).

| Code | Title | Severity | Detection summary | Likely causes | Operator checks |
|------|-------|----------|-------------------|---------------|-----------------|
| **RTU-A** | Compressor short cycling | warning | Rapid on/off cycles | Low charge, oversized unit | Run-time histogram |
| **RTU-B** | Economizer / OA damper fault | warning | OA behavior vs conditions | Actuator, sensor | OA damper vs enthalpy/OAT |
| **RTU-C** | Supply air temperature fault | warning | SAT flatline or OOB | Sensor failure | SAT trend vs outdoor conditions |
| **RTU-D** | Simultaneous heat and cool | critical | Heat + cool stages together | Control board, relay stuck | Stage status trends |

Bind rules to packaged unit `fdd_input` points (SAT, OAT, compressor cmd, …).
