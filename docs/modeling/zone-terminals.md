---
title: Zone terminals, FCU, UV
layout: default
parent: Haystack Modeling
nav_order: 4
permalink: /modeling/zone-terminals/
---

# Zone terminals, FCU, and unit ventilators

The shipped [FCU / zone_other rule family](../rules/cookbook/fcu-zone-other.md)
covers coil delivery, passing valves, ventilation feedback, sensor loss,
deadband, and heat/cool mode cycling for these controllers. Per-rule SQL and
pandas live in the
[DataFusion cookbook](../rules/cookbook/datafusion-sql-cookbook.md#fan-coil--zone_other)
and the
[Pandas cookbook](../rules/cookbook/pandas-cookbook.md#fan-coil--zone_other).
Haystack tags for each rule are on the
[SQL rules → Haystack map](sql-rules-haystack-map.html).

Open-FDD **ZONE** is a **control definition**, not "VAV boxes only."

## ZONE control (comfort + sensor FDD)

Stamp as **ZONE** (`equipType: zone_other`, `zone`, `fcu`, `fanCoil`, or standalone-DDC aliases). Applies when the asset is a **zone-level** controller or monitor:

| Shape | What it is | Typical roles / FDD |
|-------|------------|---------------------|
| **Fan-coil (FCU)** | Zone terminal with **control-valve PID** (hunting, stuck valve, valve vs zone_t) | `zone_t`, setpoints, valve cmd/feedback, occupancy when present |
| **Standalone DDC monitor** | Generic DDC watching a **standalone** local control system (sensors, maybe setpoints; not a full AHU plant) | Zone / space sensors + validity / flatline / out-of-range equations |

Both shapes:

1. Get Overview **Building schedule & zone comfort (FDD starting point)** when the zone-temp comfort gate is ON (default).
2. Run the **zone sensor-value fault equation** set (temperature performance, sensor health, related ZONE category rules) -- not AHU economizer / SAT-reset plant rules.

Do **not** stamp FCU or standalone zone DDC as `ahu`.

VAV boxes remain `equipType: vav` (zone terminals with airflow/damper). They share the **same comfort gate** for zone-temp performance rules.

## FCU / zone_other rule roles

Nine registry rules (`FCU-SENSOR-NULL`, `FCU-HTG-COIL`, `FCU-CLG-COIL`, `FCU-VALVE-PASS-HTG`, `FCU-VALVE-PASS-CLG`, `FCU-DAMPER-POS`, `FCU-CO2-DAMPER`, `FCU-DEADBAND`, `FCU-MODE-CYCLE`) select equipment from the stamp and from registry `equipment_kinds`: `zone_other`, `general`, and `ahu`. Recognized stamps win over folder or id heuristics.

| Role | How it is selected | Why |
|------|--------------------|-----|
| Master (owns a zone sensor) | `equipType` that `canonical_kind` maps to `zone_other`: `zone_other`, `zone`, `fcu`, `fanCoil`, `fanCoilUnit`, or a standalone-DDC alias | Product `kind_for` returns `zone_other`, so the family applies |
| Follower (setpoint only, no `zone_t` column) | registry kind `general` | The kind is on the FCU list. `FCU-SENSOR-NULL` forces zero hours when `zone_t` is absent, so the follower is not a dead-sensor fault. `canonical_kind` does not map the token `general`; the pandas oracle maps a resolved `GENERAL` type to `general` |
| Air handler that carries the same roles | stamp that canonicalizes to `ahu` | The kind is on the registry list. A fan coil stays on the `zone_other` stamp |

### Haystack tags the nine rules read

Preferred tags are the `haystack_point_to_role` arms in `crates/fdd_core/src/columns.rs`. Map these in the package. Empty FCU results mean the map is missing a required role.

| Need | Haystack tag | SQL role | Rules |
|------|--------------|----------|-------|
| Zone temperature | `zone-air-temp` | `zone_t` | sensor-null (optional), both coils, both passing valves |
| Own zone setpoint | `zone-air-temp-sp` | `zone_air_temp_sp` | `FCU-SENSOR-NULL` (required) |
| Discharge / supply air | `discharge-air-temp` | `sat` | both coils, both passing valves |
| Heating valve | `heating-valve` | `htg_valve_pct` | heating coil, cooling coil, both passing valves, mode cycle |
| Cooling valve | `cooling-valve` | `clg_valve_pct` | cooling coil, both passing valves, mode cycle |
| Damper command | `damper-cmd` | `damper_cmd` | `FCU-DAMPER-POS`, `FCU-CO2-DAMPER` |
| Damper feedback | `damper` | `damper_pct` | `FCU-DAMPER-POS` |
| Zone CO₂ | `zone-co2` | `zone_co2` | `FCU-CO2-DAMPER` |
| Cooling setpoint | `cooling-sp` or `zone-cooling-sp` | `cooling_sp` | `FCU-DEADBAND` |
| Heating setpoint | `heating-sp` or `zone-heating-sp` | `heating_sp` | `FCU-DEADBAND` |
| Fan proof | `fan-status` | `fan_status` | duration rules (optional; preferred) |
| Fan command fallback | `fan-cmd` | `fan_cmd` | duration rules when status is null |

Commands may be 0–1 or 0–100. Fan proof prefers `fan_status`. `fan_cmd` above 10% is the fallback. CO₂ below 300 ppm is invalid. Valve-shut tests use 0.05.

### Per-rule roles both engines need

Use this table to map a package before tip stress. The Haystack tag is the pandas column. The SQL role is the DataFusion column. Required roles are required on both engines. Fan proof is optional on both duration rules. The last column is registry `optional_roles` that the shared SQL CTE selects and the pandas predicate does not read; DataFusion injects NULL when they are absent.

Parity stays `sql_screening` until tip and field stress on issue-mapped gates. A green CI run does not close Soft-OPEN for this family.

| Rule | Confirm | Required Haystack tag (pandas) | SQL role | Optional both engines | SQL registry optional only |
|------|--------:|--------------------------------|----------|-----------------------|----------------------------|
| `FCU-SENSOR-NULL` | 0 s | `zone-air-temp-sp` | `zone_air_temp_sp` | `zone-air-temp` → `zone_t` | — |
| `FCU-HTG-COIL` | 900 s | `discharge-air-temp`, `zone-air-temp`, `heating-valve` | `sat`, `zone_t`, `htg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` | `clg_valve_pct`, `damper_cmd`, `damper_pct`, `zone_co2` |
| `FCU-CLG-COIL` | 900 s | `discharge-air-temp`, `zone-air-temp`, `cooling-valve`, `heating-valve` | `sat`, `zone_t`, `clg_valve_pct`, `htg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` | `damper_cmd`, `damper_pct`, `zone_co2` |
| `FCU-VALVE-PASS-HTG` | 900 s | `discharge-air-temp`, `zone-air-temp`, `heating-valve`, `cooling-valve` | `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` | `damper_cmd`, `damper_pct`, `zone_co2` |
| `FCU-VALVE-PASS-CLG` | 900 s | `discharge-air-temp`, `zone-air-temp`, `heating-valve`, `cooling-valve` | `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` | `damper_cmd`, `damper_pct`, `zone_co2` |
| `FCU-DAMPER-POS` | 900 s | `damper-cmd`, `damper` | `damper_cmd`, `damper_pct` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` | `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct`, `zone_co2` |
| `FCU-CO2-DAMPER` | 900 s | `zone-co2`, `damper-cmd` | `zone_co2`, `damper_cmd` | `fan-status` → `fan_status`, `fan-cmd` → `fan_cmd` | `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct`, `damper_pct` |
| `FCU-DEADBAND` | 0 s | `cooling-sp`, `heating-sp` | `cooling_sp`, `heating_sp` | — | — |
| `FCU-MODE-CYCLE` | 0 s | `heating-valve`, `cooling-valve` | `htg_valve_pct`, `clg_valve_pct` | — | — |

`FCU-SENSOR-NULL` forces zero hours when the `zone_t` / `zone-air-temp` column is absent, so a setpoint-only follower is not a dead-sensor fault. A present column that is null still runs the 90% coverage test.

### °F canonical vs °C pass-through

`sat` and `zone_t` are canonical temperature roles. Coil and passing-valve thresholds are °F (default 5.4°F, which is 3°C). On a metric session those two columns are converted to °F through `history_si`.

`cooling_sp` and `heating_sp` are not temperature roles. `FCU-DEADBAND` subtracts them in site-native °C (default minimum 1°C). Map Celsius setpoints into those two roles. A Fahrenheit number in `cooling_sp` or `heating_sp` will not be rewritten to °C, and the deadband test will not mean what the slider says.

`zone_air_temp_sp` is also pass-through. `FCU-SENSOR-NULL` only tests that it is present, so its unit does not enter a temperature comparison. The pandas quality pass skips `zone-air-temp-sp`, `cooling-sp`, and `heating-sp` on `FCU-*` rules so Fahrenheit sensor ranges do not null them first.

## Unit ventilator = CV AHU

A **unit ventilator (UV)** is an **air-handling unit, constant volume** -- same family as CV AHU.

| Stamp | Canonical kind | Display |
|-------|----------------|---------|
| `unitVentilator` / `uv` / `unit_ventilator` | `ahu` | CV AHU |
| `cv_ahu` / `cvahu` | `ahu` | CV AHU |
| `ahu` / `rtu` / `mau` / `doas` | `ahu` | AHU (or subtype label) |

UV is **not** ZONE. Do not put UV on the ZONE comfort path just because it serves one room -- use AHU constant-volume / air-handler rules and roles (`sat`, fans, OA/RA/MA when present).

## Stamp cheat sheet

| Asset | `equipType` | Kind |
|-------|-------------|------|
| VAV box | `vav` | vav |
| FCU (valve PID zone) | `fcu` / `fanCoil` | zone_other |
| Standalone zone DDC | `zone_other` / `zone` | zone_other |
| Unit ventilator | `unitVentilator` / `cv_ahu` | ahu (CV) |
| VAV AHU | `vav_ahu` / `ahu` | ahu |

Authoritative product map: `edge/src/equipment_types.rs`. Agent contract: `openfdd_agent_spec/DATA_CONTRACT.md` + `skills/openfdd-package-mapping/SKILL.md`.

## Opaque ids (DM-04)

Stamp wins over folder/id heuristics. Example: `AC_1` with `equipType: ahu` exports as **AHU** (`equipment_type_source: package`), not GENERAL. Inferred VAV→AHU parents are **proposals** (`parent_ahu_source: inferred`) and are omitted from Turtle `ofdd:parentAhu` facts until confirmed in package metadata.
