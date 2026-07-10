---
title: Rule schema (source of truth)
parent: Rule Cookbook
nav_order: 4
---

# Declarative rule schema

Every cookbook rule can be described in this schema. Implementations compile to **DataFusion SQL** (edge) and **Pandas** (off-edge parity). The schema is **standards-first** — thresholds are defaults, always site-adjustable.

## Full field list

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Stable rule ID, e.g. `RESET-SAT-MISSING` |
| `title` | string | Human-readable name |
| `taxonomy_path` | string | `{family}.{equipment_class}.{slug}` |
| `equipment_class` | enum | From [taxonomy](taxonomy.html#equipment-classes) |
| `required_points` | string[] | FDD inputs that must be assigned |
| `optional_points` | string[] | Improve accuracy when present |
| `prerequisites` | string[] | Macro IDs — occupancy, fan proven, etc. |
| `operational_gate` | object | RUN / CONDITIONAL / ALWAYS — see [operational gates](operational-gates.html) |
| `suppression_logic` | expr | When rule must not run (override, startup, bad sensor) |
| `detect_expr` | expr | Boolean fault condition → `fault_raw` |
| `confirmation_strategy` | object | `seconds`, optional `min_consecutive_samples` |
| `thresholds` | object | Named tunables with defaults and units |
| `units` | object | Unit for each point referenced |
| `evidence_fields` | string[] | Columns to include in fault evidence payload |
| `root_cause_candidates` | string[] | RCx hypotheses (not diagnoses) |
| `severity` | 1–4 | See taxonomy severity scale |
| `priority` | P0–P3 | Roadmap priority |
| `estimated_energy_impact_method` | string | Qualitative or kWh estimation approach |
| `recommended_action` | string | Operator / RCx next step |
| `validation_tests` | object[] | Scenario IDs — see [benchmark strategy](benchmark-strategy.html) |

---

## Example (YAML)

```yaml
id: RESET-SAT-MISSING
title: Supply air temperature reset not tracking outdoor air
taxonomy_path: reset.ahu.sat_oa_reset_missing
equipment_class: ahu
required_points: [sat, sat_sp, oat, fan_status]
optional_points: [occ_mode, oa_t]
prerequisites: [macro.fan_proven_on, macro.occupancy_cooling]
suppression_logic: >
  NOT (fan_status AND occ_mode != 'unoccupied')
detect_expr: >
  fan_status AND ABS(sat_sp - f(oat)) > sat_reset_err_max
  WHERE f(oat) is site SAT reset curve or linear OAT reset
confirmation_strategy:
  seconds: 900
  min_consecutive_samples: 15
thresholds:
  sat_reset_err_max: { default: 3.0, unit: "deltaF", site_adjustable: true }
  oat_reset_slope: { default: 0.25, unit: "deltaF_per_deltaF_oa", site_adjustable: true }
units:
  sat: deltaF
  sat_sp: deltaF
  oat: deltaF
evidence_fields: [timestamp, equipment_id, sat, sat_sp, oat, fan_status]
root_cause_candidates:
  - Reset schedule disabled or overridden
  - SAT SP sensor bias
  - Controller reset curve parameters wrong
severity: 2
priority: P1
estimated_energy_impact_method: Compare SAT SP deviation hours × fan energy proxy
recommended_action: Verify reset enable, OAT curve, and SAT SP source in BAS
validation_tests:
  - scenario.normal_cooling_day
  - scenario.reset_disabled_hot_day
  - scenario.missing_sat_sp
  - scenario.biased_oat_sensor
```

---

## Compilation targets

| Schema field | DataFusion SQL | Pandas |
|--------------|----------------|--------|
| `prerequisites` | `CASE WHEN …` guards or CTE from [macros](prerequisite-macros.html) | Boolean mask helpers |
| `detect_expr` | `CASE … END AS fault_raw` | `mask = …` → `fault_raw` |
| `confirmation_strategy` | API `confirmation_seconds` + comment | `confirm_fault()` helper |
| `suppression_logic` | `AND NOT (…)` in `CASE` | `mask &= ~suppress` |
| `operational_gate` | CTE / CASE → `SKIPPED_EQUIPMENT_OFF` | Gate helpers → status column |

---

## Result statuses (engine contract)

| Status | When |
|--------|------|
| `PASS` | Gate OK, enough data, no fault |
| `FAULT` | Gate OK, fault criteria met |
| `SKIPPED_MISSING_ROLES` | Required roles absent |
| `SKIPPED_EQUIPMENT_OFF` | Operational gate failed |
| `NOT_APPLICABLE_EQUIPMENT_TYPE` | Wrong equipment class |
| `ERROR` | Runtime failure |

---

## Rule documentation block (in cookbooks)

Each rule section in the SQL and Pandas cookbooks includes:

1. **Metadata table** — id, taxonomy, severity, confirmation
2. **Intent** — what fault is detected and why it matters
3. **Assumptions & tunables**
4. **False positive / negative risks**
5. **Plots to review**
6. **SQL + Pandas implementations** (linked)
7. **Validation scenarios** — normal, obvious fault, borderline, missing point, bad sensor

Template: [documentation template](doc-template.html).
