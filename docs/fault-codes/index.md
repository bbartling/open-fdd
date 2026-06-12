---
title: Fault Codes
nav_order: 8
has_children: true
---

# Fault Codes

Open-FDD uses a **check-engine** model: one building-level status (green / yellow / red) with a catalog of fixed fault codes per equipment family.

| Page | Content |
|------|---------|
| [Convention]({{ "/fault-codes/convention/" | relative_url }}) | Naming, severity, categories |
| [AHU faults]({{ "/fault-codes/ahu/" | relative_url }}) | Air handling units |
| [VAV faults]({{ "/fault-codes/vav/" | relative_url }}) | Terminal units |
| [RTU faults]({{ "/fault-codes/rtu/" | relative_url }}) | Packaged rooftops |
| [Sensor & data quality]({{ "/fault-codes/sensor-quality/" | relative_url }}) | Stale, flatline, comms |

Live catalog API: `GET /api/faults/catalog` on the Operator Bridge.
