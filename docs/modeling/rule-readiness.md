---
title: Rule readiness
parent: Haystack Modeling
nav_order: 5
---

# Rule readiness language

Agents and UIs must not report equipment as healthy when evidence is missing.

## States

| State | Meaning |
|-------|---------|
| `runnable` | Required roles present; rule may produce fault/normal hours |
| `not_runnable` | Required roles missing — do not invent substitutes |
| `not_applicable` | Diagnostic does not apply to this equipment family |
| `unknown` | Evidence insufficient to decide fault vs normal |
| `fault` / `normal` | Only when runnable and evaluated |

Missing evidence stays **null / unknown / not_runnable**, never silently
healthy.

## Heat-pump HP-1 (documented caveat — current product)

Registry (`sql_rules/registry.yaml`) for `HP-1`:

- `required_roles: [sat, zone_t, fan_cmd]`
- `optional_roles: [compressor_status, fan_status]`
- Description still says “when heating”, but heating-mode proof is not fully
  enforced in the screening SQL path.

**Important:** SQL still derives the gating fan signal from `fan_cmd` for the
final fan term. Packages with **fan status only** (no `fan_cmd`) are typically
**not runnable** for HP-1 today even if `fan_status` is mapped.

Do not silently map binary fan status into a percent `fan_cmd` just to pass
the schema. Aligning registry, SQL, cookbook, and tests is a **later**
implementation epic — not implied by this documentation.

## Heat-pump Overview matrix (caveat)

The HP health matrix may still surface AHU-shaped or economizer-shaped flags
that are **not applicable** to a water-source heat pump. Treat those as
`not_applicable` / unknown when evidence or applicability is missing — do not
count them against the unit as faults.

Redesigning `hp_health_matrix_v1` around HP-only diagnostics is deferred.

## Agent checklist before claiming “FDD ready”

1. Stamp types + compact maps for every equipment CSV.
2. Confirm required roles for the target rules exist post-import.
3. Report blocked rules and missing BAS points explicitly.
4. Never fabricate physical evidence columns.
