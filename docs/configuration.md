---
title: Configuration
nav_order: 12
---

# Configuration

This page describes how to **configure YAML rules** and engine behavior when using the **`open_fdd`** library directly. There is **no** required platform database or HTTP service in this repository.

---

## Rule YAML

Rules are loaded with **`load_rule()`** / **`RuleRunner`** (see [Rules overview](rules/overview)).

Typical fields include:

| Field | Role |
|-------|------|
| **`name`**, **`description`** | Human-readable metadata |
| **`equipment_type`** | Optional filter for which equipment a rule applies to |
| **`type`** | Check type (`bounds`, `flatline`, `expression`, …) |
| **`params`** | Check-specific parameters (thresholds, `rolling_window`, …) |
| **`column_map`** | Mapping from logical point names to DataFrame columns (dict or manifest path) |

Use **`fdd_strict_rules`**-style tightening in **your** caller if you want stricter validation of column maps and dtypes before evaluation (see [Expression rule cookbook](expression_rule_cookbook)).

---

## Column maps

- **Inline dict** — simplest: `{ "SAT": "SupplyAirTemp" }` keys match placeholders in the rule.
- **Manifest YAML** — see [Column map resolvers](column_map_resolvers) for **`ManifestColumnMapResolver`** and composite patterns.

---

## Environment variables

The **`open-fdd`** wheel does **not** read a fixed `OFDD_*` namespace. Your **application** may use env vars to locate rule directories or data files; that is entirely under your control.

---

## Related topics

- [Rules overview](rules/overview)
- [Engine-only / IoT](howto/engine_only_iot)
- [Getting started](getting_started)
