---
title: Convention
parent: Fault Codes
nav_order: 1
---

# Fault code convention

## Format

`FAMILY-SUFFIX` — suffix is **1–3 letters** (e.g. `VAV-C`, `AHU-B`). Numeric suffixes like `VAV-03` are avoided (collision with physical equipment names).

## Categories

| Category | Meaning |
|----------|---------|
| `performance_degradation` | Efficiency or capacity drift |
| `simultaneous_heat_cool` | Heating and cooling fighting |
| `sensor_fault` | Flatline, OOB, inconsistent readings |
| `io_fault` | Command vs feedback mismatch |

## Severity

| Level | Operator response |
|-------|-------------------|
| `info` | Log; trend for maintenance window |
| `warning` | Investigate within days |
| `critical` | Prompt attention; may affect comfort/energy significantly |

## Linking rules

In Rule Lab, set `fault_code` on the rule metadata. Batch FDD aggregates hits into `GET /api/faults/status` by family.

## Cookbook mapping

Each catalog entry lists `cookbook_patterns` (e.g. `flatline_1h`, `mixing_envelope`, `rate_of_change`) — see [Expression cookbook (Arrow-native)](../rule-cookbook/expression-cookbook).

Legacy pandas `type: expression` YAML rules are **not** used on the edge in 3.x; translate to `rules_py` Arrow modules and bind **`fault_code`** in Rule Lab.
