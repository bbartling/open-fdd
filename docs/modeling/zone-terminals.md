---
title: Zone terminals, FCU, UV
layout: default
parent: Haystack Modeling
nav_order: 4
permalink: /modeling/zone-terminals/
---

# Zone terminals, FCU, and unit ventilators

Open-FDD **ZONE** is a **control definition**, not “VAV boxes only.”

## ZONE control (comfort + sensor FDD)

Stamp as **ZONE** (`equipType: zone_other`, `zone`, `fcu`, `fanCoil`, or standalone-DDC aliases). Applies when the asset is a **zone-level** controller or monitor:

| Shape | What it is | Typical roles / FDD |
|-------|------------|---------------------|
| **Fan-coil (FCU)** | Zone terminal with **control-valve PID** (hunting, stuck valve, valve vs zone_t) | `zone_t`, setpoints, valve cmd/feedback, occupancy when present |
| **Standalone DDC monitor** | Generic DDC watching a **standalone** local control system (sensors, maybe setpoints; not a full AHU plant) | Zone / space sensors + validity / flatline / out-of-range equations |

Both shapes:

1. Get Overview **Building schedule & zone comfort (FDD starting point)** when the zone-temp comfort gate is ON (default).
2. Run the **zone sensor-value fault equation** set (temperature performance, sensor health, related ZONE category rules) — not AHU economizer / SAT-reset plant rules.

Do **not** stamp FCU or standalone zone DDC as `ahu`.

VAV boxes remain `equipType: vav` (zone terminals with airflow/damper). They share the **same comfort gate** for zone-temp performance rules.

## Unit ventilator = CV AHU

A **unit ventilator (UV)** is an **air-handling unit, constant volume** — same family as CV AHU.

| Stamp | Canonical kind | Display |
|-------|----------------|---------|
| `unitVentilator` / `uv` / `unit_ventilator` | `ahu` | CV AHU |
| `cv_ahu` / `cvahu` | `ahu` | CV AHU |
| `ahu` / `rtu` / `mau` / `doas` | `ahu` | AHU (or subtype label) |

UV is **not** ZONE. Do not put UV on the ZONE comfort path just because it serves one room — use AHU constant-volume / air-handler rules and roles (`sat`, fans, OA/RA/MA when present).

## Stamp cheat sheet

| Asset | `equipType` | Kind |
|-------|-------------|------|
| VAV box | `vav` | vav |
| FCU (valve PID zone) | `fcu` / `fanCoil` | zone_other |
| Standalone zone DDC | `zone_other` / `zone` | zone_other |
| Unit ventilator | `unitVentilator` / `cv_ahu` | ahu (CV) |
| VAV AHU | `vav_ahu` / `ahu` | ahu |

Authoritative product map: `edge/src/equipment_types.rs`. Agent contract: `openfdd_agent_spec/DATA_CONTRACT.md` + `skills/openfdd-package-mapping/SKILL.md`.
