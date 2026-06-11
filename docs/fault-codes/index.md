---
title: Fault Codes
nav_order: 8
has_children: true
---

# Fault Codes

Open-FDD uses a **check-engine** model: one building-level status (green / yellow / red) with a catalog of fixed fault codes per equipment family.

| Page | Content |
|------|---------|
| [Convention]({% link fault-codes/convention.md %}) | Naming, severity, categories |
| [AHU faults]({% link fault-codes/ahu.md %}) | Air handling units |
| [VAV faults]({% link fault-codes/vav.md %}) | Terminal units |
| [RTU faults]({% link fault-codes/rtu.md %}) | Packaged rooftops |
| [Sensor & data quality]({% link fault-codes/sensor-quality.md %}) | Stale, flatline, comms |

Live catalog API: `GET /api/faults/catalog` on the Operator Bridge.
