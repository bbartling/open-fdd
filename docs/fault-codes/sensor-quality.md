---
title: Sensor and data quality
parent: Fault Codes
nav_order: 5
---

# Sensor and data quality

Sensor faults use cookbook patterns **`flatline_1h`**, **`oob_rolling`**, **`rate_of_change`**, and **`mixing_envelope`**. Full thresholds: [GL36 & sensor patterns]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#sensor-validation-bounds-flatline-rate-of-change).

## Catalog codes

| Code | Title | Severity | Pattern | Detection summary |
|------|-------|----------|---------|-------------------|
| **BLD-B** | Outdoor air sensor fault | warning | flatline, oob, rate_of_change | OAT flatline, OOB, or unrealistic spike |
| **BLD-D** | Stale telemetry | critical | stale_points | No new samples within threshold |
| **AHU-C** | SAT sensor fault | warning | flatline_1h, oob_rolling | Supply air temp stuck or out of band |
| **AHU-D** | MAT inconsistent with OAT/RAT | warning | mixing_envelope | Mixed air outside OAT–RAT envelope |
| **VAV-C** | Zone temperature sensor fault | warning | flatline_1h, oob_rolling | Zone temp stuck or 55–90 °F band breach |
| **RTU-C** | Supply air temperature fault | warning | flatline_1h, oob_rolling | Packaged unit SAT fault |
| **CH-D** | CHW supply temperature sensor fault | warning | flatline_1h, oob_rolling | Plant CHW sensor fault |
| **DC-C** | Datacom sensor anomaly | warning | flatline_1h | CRAH/room sensor flatline or RH OOB |
| **HP-D** | Discharge/suction temperature sensor fault | warning | flatline_1h, oob_rolling | Heat pump refrigerant/air temp sensor |

## Default bounds (imperial, occupied)

| Sensor | Min | Max | Flatline tol | Max Δ/hr |
|--------|-----|-----|--------------|----------|
| Zone temp | 55 °F | 90 °F | 0.10 °F | 4 °F |
| Supply air temp | 50 °F | 110 °F | 0.15 °F | 8 °F |
| Return air temp | 55 °F | 95 °F | 0.10 °F | 3 °F |
| Duct static | −0.5 | 3.0 inH₂O | 0.02 | 0.5 |
| RH | 0 % | 100 % | 1.0 % | 15 % |
| CHW | 40 °F | 90 °F | 0.10 °F | 4 °F |
| HW | 70 °F | 200 °F | 0.15 °F | 6 °F |
| Condenser water | 50 °F | 110 °F | 0.15 °F | 5 °F |
| CO₂ (occupied) | 400 ppm | 1000 ppm | 5 ppm | 200 ppm |

Return-air checks use **narrow bands**; when MAT/OAT/RAT are available, prefer **mixing envelope** over RAT bounds alone.

## Communication quality

- Monitor poll cycle timestamps in dashboard.
- Use `stale_points` for dropout detection (**BLD-D**).
- Do not confuse **comm loss** with **equipment fault** — verify BACnet device online before dispatching mechanical.

## Operator workflow

1. Confirm **BLD-D** (stale) is resolved before trusting other sensor codes.
2. Cross-check **BLD-B** OAT against weather service or JSON API driver.
3. For **VAV-C** / **AHU-C**, compare neighbor zones / coil behavior before replacing sensor.
