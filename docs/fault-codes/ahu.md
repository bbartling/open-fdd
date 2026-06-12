---
title: AHU faults
parent: Fault Codes
nav_order: 2
---

# AHU faults

Air handling unit codes (sample from catalog).

| Code | Title | Severity | Detection summary | Likely causes | Operator checks |
|------|-------|----------|-------------------|---------------|-----------------|
| **AHU-A** | Supply fan performance degradation | warning | Spread/runtime vs baseline | Belt slip, dirty filters, VFD limit | Trend speed vs airflow; filter dP |
| **AHU-B** | Simultaneous heating and cooling | critical | Heat + cool outputs active together | Sequencing bug, leaking valve | Trend coil commands; valve feedback |
| **AHU-C** | SAT sensor fault | warning | Flatline / OOB SAT | Failed sensor, bad calibration | SAT trend; compare to coil discharge |
| **AHU-D** | MAT inconsistent with OAT/RAT | warning | MAT outside OAT–RAT envelope | MAT/OAT/RAT sensor errors | Verify damper positions; cross-check OAT |
| **AHU-E** | Economizer not economizing | warning | Free cool available, OA minimum | Stuck damper, lockout | OA damper vs OAT trend |
| **AHU-F** | Damper command vs feedback mismatch | warning | Cmd ≠ feedback | Stuck actuator, linkage | Compare cmd/feedback trends |

**Example rule:** `flatline_1h` on SAT → tag **AHU-C**. Recipe: [Python recipes]({{ "/rule-cookbook/python-recipes/" | relative_url }}).
