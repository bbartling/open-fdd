---
title: VAV faults
parent: Fault Codes
nav_order: 3
---

# VAV faults

Variable air volume terminal codes (sample).

| Code | Title | Severity | Detection summary | Likely causes | Operator checks |
|------|-------|----------|-------------------|---------------|-----------------|
| **VAV-A** | Zone heating/cooling overlap | warning | Heat and cool at terminal | Reheat valve stuck, SAT too low | Zone temp vs SAT; valve cmd |
| **VAV-B** | Poor zone temperature control | warning | Persistent deviation from setpoint | Oversized box, bad tuning | PI loop trends; occupancy |
| **VAV-C** | Zone temperature sensor fault | warning | Flatline / OOB zone temp | Failed zone sensor | Flatline test; compare to neighbor zones |
| **VAV-D** | Minimum airflow not met | warning | Flow below minimum cmd | Damper stuck, pressure issue | Airflow vs damper cmd |
| **VAV-E** | Discharge temp deviation from SAT | warning | DAT far from SAT setpoint | Coil issue, sensor drift | DAT vs SAT SP |

**Example rule:** `oob_rolling` on zone temp → **VAV-C** or comfort bounds per site policy.
