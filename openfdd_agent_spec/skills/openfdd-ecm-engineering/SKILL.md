---
name: openfdd-ecm-engineering
description: >-
  Use when migrating or changing generic ECM math in open_fdd.ecm_engineering
  or deleting vibe20 twins after parity. Triggers on: ECM, fan affinity,
  scheduling bins, boiler efficiency, esco calculator, OPENFDD_ECM_TWINS,
  Milestone A Phase 4.
---

# ECM engineering

Canonical generic math: `open_fdd.ecm_engineering`.
EnergyPlus-specific code stays in vibe20.

## Migration pattern

```text
inventory → golden/characterize → implement/confirm in Open-FDD
→ parity → switch adapter → delete twin → remove dead imports → docs
```

## Already delegated (do not re-port)

fan_affinity, schedule_reduction, outside_air_sensible, kw_per_ton_improvement,
boiler_efficiency_improvement, scheduling_fan/cooling/heating_bins.

Keepers: playground `vibe_code_apps_20/docs/OPENFDD_ECM_TWINS.md`.

## Result contracts

Return enough detail (summary, bins, assumptions, warnings, provenance) so
vibe20 adapters do not recompute formulas.
