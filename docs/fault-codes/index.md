---
title: Fault Codes
nav_order: 8
has_children: true
---

# Fault Codes

Open-FDD uses a **check-engine** model: one building-level status (green / yellow / red) with a catalog of fixed fault codes per equipment family.

| Page | Content |
|------|---------|
| [Convention](convention) | Naming, severity, categories |
| [AHU faults](ahu) | Air handling units |
| [VAV faults](vav) | Terminal units |
| [RTU faults](rtu) | Packaged rooftops |
| [Sensor & data quality](sensor-quality) | Stale, flatline, comms |

Live catalog API: `GET /api/faults/catalog` on the Operator Bridge.
