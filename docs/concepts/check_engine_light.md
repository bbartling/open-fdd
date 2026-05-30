---
title: Building check-engine light
parent: Concepts
nav_order: 4
---

# Building check-engine light

The building has one **GREEN / YELLOW / RED** light on the home dashboard, like a
car. A tree underneath breaks faults down by equipment. The local Ollama agent
drives the light but uses a **fixed** code list — it never invents codes.

## Fixed fault codes

Codes live in `fault_catalog.py` and are served at `GET /api/faults/catalog`.
APIs that accept a `code` reject unknown values. FDD covers four categories only:

| Category | Meaning |
|----------|---------|
| `performance_degradation` | Efficiency/capacity drifting from baseline. |
| `simultaneous_heat_cool` | Heating and cooling fighting each other. |
| `sensor_fault` | Flatline / out-of-range / drift / inconsistent sensors. |
| `io_fault` | Command vs feedback mismatch, stuck actuators, stale points. |

This is **not** classic BAS alarm-and-dial-out.

## Equipment families

`AHU`, `VAV`, `HEATPUMP`, `GEO`, `CHILLER`, `DATACENTER`, `BUILDING` — each owns a
short code list (browse them on the dashboard **Fault catalog** page).

## How it lights up

Tag a Rule Lab rule with a `fault_code` → the scheduled FDD run flags faults →
results group by family in `GET /api/faults/status`. `ok → green`,
`warning → yellow`, `critical → red`.

See also: `skills/building-check-engine/SKILL.md`.
