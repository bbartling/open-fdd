---
title: Sensor and data quality
parent: Fault Codes
nav_order: 5
---

# Sensor and data quality

| Code | Title | Severity | Detection summary | Likely causes | Operator checks |
|------|-------|----------|-------------------|---------------|-----------------|
| **BLD-B** | Outdoor air sensor fault | warning | OAT flatline / unrealistic | Sensor exposure, failed probe | Compare to weather service |
| **BLD-D** | Stale telemetry | warning | No new samples within threshold | Poll driver down, device offline | Poll health; BACnet comms |
| **DC-C** | Datacom sensor anomaly | warning | CRAH/room sensor flatline | Failed sensor | Row-level flatline recipe |

## Communication quality

- Monitor poll cycle timestamps in dashboard.
- Use `stale_points` cookbook pattern for dropout detection.
- Do not confuse **comm loss** with **equipment fault** — verify BACnet device online before dispatching mechanical.

## Alarm console quality

When integrating with BMS alarms (future/external), map Open-FDD codes to operator work orders — Open-FDD itself is **analytics-first**, not a dial-out alarm server.
