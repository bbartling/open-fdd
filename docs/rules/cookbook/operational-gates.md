---
title: Operational gates
parent: Rule Cookbook
nav_order: 12
permalink: /rules/cookbook/operational-gates/
---

# Operational gates — when rules may evaluate

A large portion of FDD rules should only evaluate while the associated system has **proven operation**. Otherwise startup, shutdown, unoccupied, and dead-equipment periods inflate fault hours or false `PASS` totals.

**Hard rule for cookbook maintainers:** this page and the expression cookbooks are **additive**. Never delete, shorten, or “vibe-code out” existing FC4, CTRL-2, or other rule sections when adding gates or new rules.

## Core refinement

> **Do not use one universal “motor running” filter.**  
> Use equipment-specific operational gates: fan running, pump running, compressor running, airflow proven, hydronic flow proven, occupied, or control loop active.

Separate these conditions:

| Condition | Meaning | Example |
|-----------|---------|---------|
| `fan_running` | Fan proven on or speed/current/airflow evidence | speed &gt; 5% or status ON |
| `fan_at_full_speed` | Near-full output (FC1-style) | command/speed ≥ 85–90% |
| `loop_enabled` | Control loop / equipment enable | PID enable, plant enable |

FC1 must keep **both** `fan_running` **and** `fan_at_full_speed` — do not replace the full-fan threshold with a generic running gate.

## Result status contract (six statuses)

Every equipment/rule evaluation must produce exactly one status:

| Status | Meaning |
|--------|---------|
| `PASS` | Applicable, enough active data, no fault |
| `FAULT` | Applicable, fault criteria met (after confirm when used) |
| `SKIPPED_MISSING_ROLES` | Required roles/columns absent |
| `SKIPPED_EQUIPMENT_OFF` | Gate failed — equipment not proven operating |
| `NOT_APPLICABLE_EQUIPMENT_TYPE` | Wrong equipment class for this rule |
| `ERROR` | Engine/SQL/runtime failure |

An AHU off all night must **not** accumulate hours of `PASS`. Prefer:

```json
{
  "rule_id": "FC8",
  "status": "SKIPPED_EQUIPMENT_OFF",
  "applicable": false,
  "active_sample_count": 0,
  "fault_hours": null,
  "notes": "Supply fan was not proven on during the analysis period."
}
```

`SCHED-1` and `CMD-1` must **not** use a motor-running gate — that would hide failure-to-start, failure-to-stop, and after-hours operation.

## Gate types

| Type | Use when |
|------|----------|
| **RUN** | Require fan, pump, compressor, or flow proof |
| **CONDITIONAL** | Occupancy, demand, actuator command, or point-specific activity |
| **ALWAYS** | Evaluate regardless of motor state |

## Canonical 50 + PID-HUNT-1 gate table

| # | Rule | Gate | Recommended operational filter |
|--:|------|------|--------------------------------|
| 1 | `SV-RANGE` | ALWAYS | Sensor range validation continuous |
| 2 | `SV-FLATLINE` | CONDITIONAL | Process sensors active-only; OAT continuous |
| 3 | `SV-SPIKE` | ALWAYS | Spike detection continuous |
| 4 | `SV-STALE` | ALWAYS | Stale data continuous |
| 5 | `SV-4` | RUN | AHU fan or airflow proven before MAT/OAT/RAT envelope |
| 6 | `FC1` | RUN | Supply fan running **and** full-fan threshold |
| 7 | `FC2` | RUN | Supply fan or airflow proven |
| 8 | `FC3` | RUN | Supply fan or airflow proven |
| 9 | `FC4` | RUN | Fan running and associated control loop active |
| 10 | `FC5` | RUN | Supply fan or airflow proven |
| 11 | `FC6` | RUN | Supply fan or airflow proven |
| 12 | `FC7` | RUN | Supply fan running plus heating enabled |
| 13 | `FC8` | RUN | Supply fan running plus economizer mode active |
| 14 | `FC9` | RUN | Supply fan running plus economizer mode active |
| 15 | `FC10` | RUN | Supply fan running plus cooling/economizer mode |
| 16 | `FC11` | RUN | Supply fan running plus cooling/economizer mode |
| 17 | `FC12` | RUN | Supply fan running plus cooling active |
| 18 | `FC13` | RUN | Supply fan running plus cooling demand/valve |
| 19 | `FC14` | RUN | Supply fan running plus applicable coil mode |
| 20 | `FC15` | RUN | Supply fan running plus applicable coil mode |
| 21 | `AHU-SATDEV` | RUN | Supply fan running and startup delay complete |
| 22 | `AHU-DUCTHI` | RUN | Supply fan running |
| 23 | `AHU-SIMUL-HEAT-COOL` | RUN | AHU enabled / fan running |
| 24 | `ECON-1` | RUN | Supply fan running and economizer available |
| 25 | `ECON-2` | RUN | Supply fan running and occupied/ventilation active |
| 26 | `ECON-3` | RUN | Supply fan running and economizer mode applicable |
| 27 | `ECON-4` | RUN | Supply fan running; stable MAT/RAT/OAT |
| 28 | `ECON-5` | RUN | Supply fan running plus preheat/economizer context |
| 29 | `OA-1` | RUN | Supply fan or measured airflow proven |
| 30 | `DMP-1` | CONDITIONAL | Actuator commanded; normally AHU running too |
| 31 | `VAV-1` | CONDITIONAL | Occupied; AHU airflow preferred as context |
| 32 | `VAV-3` | RUN | AHU airflow available; zone occupied when applicable |
| 33 | `VAV-4` | RUN | AHU airflow available and VAV loop active |
| 34 | `VAV-5` | RUN | AHU airflow available |
| 35 | `VAV-7` | RUN | AHU airflow available |
| 36 | `VAV-REHEAT-STUCK` | RUN | AHU airflow plus reheat demand/command |
| 37 | `CHW-1` | RUN | CHW pump/flow proven and plant enabled |
| 38 | `CHW-2` | RUN | CHW pump/flow proven |
| 39 | `CHW-3` | RUN | Chiller or CHW loop operating |
| 40 | `CHW-4` | RUN | CHW pump/flow proven plus cooling demand |
| 41 | `HP-1` | RUN | Compressor, fan, or HP mode proven |
| 42 | `WX-1` | ALWAYS | Weather validation continuous |
| 43 | `WX-2` | ALWAYS | Weather validation continuous |
| 44 | `OAT-METEO` | ALWAYS | OAT comparison continuous |
| 45 | `TRIM-1` | RUN | AHU fan running and terminal requests available |
| 46 | `TRIM-3` | RUN | HW pump/plant enabled or heating demand |
| 47 | `TRIM-4` | RUN | CHW pump/plant enabled or cooling demand |
| 48 | `SCHED-1` | ALWAYS | Must cover scheduled-on and scheduled-off |
| 49 | `CMD-1` | ALWAYS | Failure-to-start and failure-to-stop |
| 50 | `VLV-1` | CONDITIONAL | Valve commanded/demanded; add flow proof for thermal response |
| 51 | `PID-HUNT-1` | CONDITIONAL | Prefer `loop_enabled`; else evaluate when output is active |

### Count (canonical 50)

```text
Require operating/motor/flow proof: 38
Conditional activity gate:          4
No motor gate:                       8
---------------------------------------
Total:                              50
```

`PID-HUNT-1` is the **51st** independently useful rule (see [PID-HUNT-1](pid-hunt-1.html)). Keep FC4 as the equipment-specific mode-transition diagnostic; both may share hunting mathematics where appropriate.

### Eight rules that must not use a motor-running filter

```text
SV-RANGE, SV-SPIKE, SV-STALE, WX-1, WX-2, OAT-METEO, SCHED-1, CMD-1
```

## Evidence order (do not rely only on `fan_cmd`)

```text
1. Motor status/proof
2. VFD speed feedback
3. Current or power proof
4. Airflow, duct pressure, or hydronic flow proof
5. Command as fallback
```

Suggested roles:

```yaml
fan_status:
fan_cmd:
fan_speed_feedback:
fan_current:
fan_power:
airflow_proof:
pump_status:
pump_cmd:
pump_speed_feedback:
pump_current:
water_flow:
compressor_status:
equipment_enable:
occupied:
control_loop_active:
control_output_pct:   # PID-HUNT-1
loop_enabled:         # PID-HUNT-1 optional
```

Resolved AHU gate:

```text
fan_running =
    fan_status == ON
    OR fan_speed_feedback > 5%
    OR fan_current > configured threshold
    OR airflow_proof == ON
    OR (command_fallback_allowed AND fan_cmd > 5%)
```

## Startup / shutdown delays (tunable)

```yaml
fan_startup_delay_seconds: 300
thermal_startup_delay_seconds: 600
plant_startup_delay_seconds: 900
shutdown_exclusion_seconds: 300
minimum_active_coverage_pct: 80
```

Examples: duct static 2–5 min after fan start; mixed-air 5–10 min; SAT/coil 10–15 min; CHW ΔT 10–20 min.

## Registry-level `operational_gate` (target schema)

Both Pandas and DataFusion must apply the same gate **before** the rule condition and denominator:

```yaml
operational_gate:
  type: fan_running
  required: true
  accepted_roles:
    - fan_status
    - fan_speed_feedback
    - fan_current
    - airflow_proof
    - fan_cmd
  command_fallback_allowed: true
  startup_delay_seconds: 600
  minimum_active_coverage_pct: 80
```

Plant example:

```yaml
operational_gate:
  type: hydronic_flow
  required: true
  accepted_roles:
    - chw_flow
    - pump_status
    - pump_speed_feedback
    - pump_current
    - pump_cmd
  startup_delay_seconds: 900
```

See also [prerequisite macros](prerequisite-macros.html) (`macro.fan_proven_on`, `macro.fan_running`, `macro.hydronic_flow_proven`).

## Known registry inconsistency (cleanup target)

Shipped `sql_rules/registry.yaml` currently requires `fan_cmd` for FC1–FC3, FC7, ECON-1, ECON-4, but FC8–FC13 do not consistently require a fan-running role. FC1 uses `fan_cmd >= 0.87` (near-full fan), which is **not** the same as “fan running.” Aligning gates is a priority before trusting full 50-rule BUILDING_100 results — without removing existing cookbook SQL/Pandas expressions.
