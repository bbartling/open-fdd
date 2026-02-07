---
title: Config Schema
nav_order: 23
---

# Config Schema

Machine-readable and human-readable schema for open-fdd rule YAML configs.

---

## Rule types (enumeration)

| Type | Built-in | Description |
|------|----------|-------------|
| `expression` | No | Custom pandas/NumPy expression |
| `bounds` | Yes | Value outside [low, high] |
| `flatline` | Yes | Sensor stuck (rolling spread &lt; tolerance) |
| `hunting` | Yes | Excessive AHU state changes |
| `oa_fraction` | Yes | OA fraction vs design minimum |
| `erv_efficiency` | Yes | ERV effectiveness out of range |

---

## Equipment types (enumeration)

| Value | Scope |
|-------|-------|
| `AHU` | Air-handling unit |
| `VAV_AHU` | VAV air-handling unit |
| `VAV` | VAV zone |
| `AHU_ERV` | AHU with ERV |

---

## Rule YAML structure

### Required fields (all rules)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Rule identifier |
| `type` | string | One of rule types above |
| `flag` | string | Output column name (e.g. `rule_a_flag`) |
| `inputs` | object | Map of input key → config |

### Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Human-readable description |
| `equipment_type` | list[string] | Filter: only run when model matches |
| `params` | object | Thresholds, constants |
| `expression` | string | For `type: expression` only |

### Input config (per input)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `column` | string | Yes* | DataFrame column name (fallback) |
| `brick` | string | Yes* | BRICK class name |
| `bounds` | array or object | For `bounds` type | `[low, high]` or `{imperial: [...], metric: [...]}` |

*Either `column` or `brick`; `column_map` can override at runtime.

### Params (common)

| Param | Type | Used by | Description |
|-------|------|---------|-------------|
| `units` | string | bounds | `imperial` or `metric` |
| `tolerance` | float | flatline | Spread threshold |
| `window` | int | flatline, hunting | Rolling window (samples) |
| `delta_os_max` | int | hunting | Max state changes in window |
| `ahu_min_oa_dpr` | float | hunting, oa_fraction | Min OA damper position |

---

## JSON Schema (machine-readable)

See `config_schema.json` in this directory for a JSON Schema draft. Not enforced at runtime; use for validation tooling and agent correctness.
