---
title: Public FDD taxonomy
parent: Rule Cookbook
nav_order: 3
---

# Canonical public FDD taxonomy

Neutral, standards-first taxonomy for Open-FDD rule cookbooks. Names are **generic semantic variables** — portable across Haystack-modeled sites and generic BAS telemetry. Not tied to any vendor namespace.

## Literature anchors (public)

| Source | Use in this taxonomy |
|--------|----------------------|
| [ASHRAE Guideline 36](https://www.ashrae.org/technical-resources/bookstore/guideline-36-high-performance-sequences-of-operation-for-hvac-systems) AFDD addenda | AHU supervisory faults, internal variables, confirmation delays |
| Berkeley Lab HVAC fault taxonomy | Equipment classes, fault categories, symptom → cause mapping |
| Berkeley Lab FDD benchmarking datasets | Regression scenarios, expected fault signatures |
| PNNL AIRCx / re-tuning literature | Reset, schedule, override, performance KPI opportunities |
| NIST HVAC-Cx guidance | AHU/VAV commissioning checks transferable to continuous FDD |
| [Project Haystack](https://project-haystack.org/) | Equipment tags, point semantics |

---

## Equipment classes

| Class ID | Description | Example Haystack tags |
|----------|-------------|------------------------|
| `ahu` | Air handling unit | `ahu`, `airHandlingEquip` |
| `vav` | Variable air volume terminal | `vav`, `vavZoneEquip` |
| `rtu` | Rooftop unit | `rooftopUnit` |
| `fcu` | Fan coil unit | `fanCoilUnit` |
| `plant.chw` | Chilled-water plant | `chillerPlant`, `chilledWaterPlant` |
| `plant.hw` | Hot-water / boiler plant | `hotWaterPlant`, `boilerPlant` |
| `plant.tower` | Cooling tower | `coolingTower` |
| `hp` | Heat pump | `heatPump` |
| `sensor.weather` | Weather station | `weatherStation` |
| `site` | Whole-building / meter | `site`, `elecMeter` |

---

## Rule families (top level)

| Family ID | Name | Typical symptoms |
|-----------|------|------------------|
| `sensor.quality` | Sensor validation (sweep) | SV-RANGE, SV-FLATLINE, SV-SPIKE, SV-STALE, SV-RATE |
| `control.loop` | Control loop | PID-HUNT-1, FC4 hunting, setpoint tracking, simultaneous heat/cool |
| `economizer` | Economizer & OA | Stuck closed, unfavorable economizing, low OA fraction |
| `ventilation` | Ventilation | Low OA, preheat over-conditioning, DCV miss |
| `schedule` | Schedule & occupancy | Unoccupied runtime, setback miss, morning warm-up fail |
| `reset` | Reset logic | Missing SAT/CHW/HW/DP reset, setpoint too high/low |
| `override` | Overrides | Persistent manual override, bypass active |
| `actuator.leakage` | Valve / damper leakage | Flow/temp when commanded closed |
| `plant.performance` | Plant performance | CHW ΔT/DP/flow, CHW-NOLOAD-1, CW approach/fan/opt |
| `terminal.vav` | VAV terminals | Comfort band, reheat, damper stuck, airflow bias |
| `command.status` | Command vs status | Fan/pump/damper cmd ≠ feedback |
| `kpi.advisory` | Performance KPI | Trim/respond, energy opportunity scoring |
| `safety.envelope` | Safety envelopes | GL36-style MAT/SAT/OAT consistency checks |

---

## Taxonomy path format

```
{family}.{equipment_class}.{rule_id}
```

Examples:

- `sensor.quality.site.sv_range`
- `control.loop.generic.pid_hunt_1`
- `control.loop.ahu.fc1_duct_static_low`
- `schedule.ahu.sched_1_unoccupied_runtime`
- `schedule.ahu.sched_247_always_on`

---

## Severity scale

| Level | Label | Typical response |
|-------|-------|------------------|
| 1 | Advisory | Log, trim/respond, RCx queue |
| 2 | Warning | Operator review within 24 h |
| 3 | Fault | Work order, comfort/energy impact |
| 4 | Critical | Immediate — safety or major waste |

---

## Priority scale (implementation roadmap)

| Priority | Meaning |
|----------|---------|
| P0 | In both cookbooks today, parity verified |
| P1 | High public-literature value — draft in v2 expansion |
| P2 | Common RCx find — scheduled next |
| P3 | Niche / site-specific — document pattern only |

See [gap matrix](gap-matrix.html), [parity matrix](parity-matrix.html), and [roadmap](roadmap.html).
