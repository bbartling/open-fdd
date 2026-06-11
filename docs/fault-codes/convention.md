---
title: Convention
parent: Fault Codes
nav_order: 1
---

# Fault code convention

## Format (Grade-A, 3.0.18+)

**Short stable code:** `FAMILY-SUBSYSTEM-NNN` — e.g. `AHU-ECON-001`, `CHW-DT-001`, `DATA-STAL-001`.

**Semantic ID:** dotted `canonical_id` — e.g. `ahu.economizer.not_using_free_cooling`.

**Legacy letter codes** (`AHU-E`, `VAV-C`) remain **aliases** in `open_fdd/faults/catalog/*.yaml` until bridge sync completes.

| Field | Example |
|-------|---------|
| `code` | `AHU-ECON-001` |
| `canonical_id` | `ahu.economizer.not_using_free_cooling` |
| `family` | `AHU`, `VAV`, `CHW`, `DATA`, `CRS`, … |
| `rule_doc_path` | Link to rule cookbook recipe |

Full schema: `open_fdd/faults/schema.py`. Catalog loader: `open_fdd/faults/catalog.py`.

## Categories (Grade-A)

| Category | Meaning |
|----------|---------|
| `energy` | Waste, reset stuck, plant inefficiency |
| `comfort` | Setpoint not met, poor zone performance |
| `reliability` | Short cycling, staging, equipment stress |
| `maintenance` | Leaking valves, filters, fouling proxies |
| `indoor_air_quality` | Ventilation shortfall, humidity |
| `healthcare_risk` | Pressure, isolation, critical-space excursions |
| `data_quality` | Stale, flatline, OOB, missing historian |
| `controls_integrity` | Overrides, chatter, schedule violations |

## Severity

| Level | Operator response |
|-------|-------------------|
| `info` | Log; trend for maintenance window |
| `low` | Review in routine rounds |
| `medium` | Investigate within days |
| `high` | Prompt attention; comfort/energy impact likely |
| `critical` | Immediate operational risk (especially `healthcare_risk`) |

## Linking rules

In Rule Lab, set `fault_code` on the rule metadata. Batch FDD aggregates hits into `GET /api/faults/status` by family.

## Cookbook mapping

Each catalog entry lists `cookbook_patterns` (e.g. `flatline_1h`, `mixing_envelope`, `rate_of_change`) — see [Expression cookbook (Arrow-native)]({% link rule-cookbook/expression-cookbook.md %}).

Legacy pandas `type: expression` YAML rules are **not** used on the edge in 3.x; translate to `rules_py` Arrow modules and bind **`fault_code`** in Rule Lab.
