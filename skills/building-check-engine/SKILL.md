---
name: building-check-engine
description: "Drive the building check-engine light (GREEN/YELLOW/RED) using the FIXED fault-code catalog. Use when reporting/clearing building faults, tagging rules with fault codes, or asking what can go wrong with HVAC. The agent reuses catalog codes and never invents them."
---

# Building check-engine light

## The one rule

**Codes are fixed. Pick from the catalog; never invent one.** The catalog lives
in `fault_catalog.py` and is served at `GET /api/faults/catalog` (also in the
agent context as `fault_codes`). Any API taking a `code` rejects unknowns (400).

## Scope

FDD covers four categories only: `performance_degradation`,
`simultaneous_heat_cool`, `sensor_fault`, `io_fault`. It is **not** classic BAS
nuisance alarming / dial-out — decline those and point here.

Families: `AHU`, `VAV`, `HEATPUMP`, `GEO`, `CHILLER`, `DATACENTER`, `BUILDING`.

## Quick start

- `rules.save` (or `POST /api/rules/save`) — set `fault_code` so scheduled runs
  light the right family.
- `building.set_alerts` (or `PUT /api/building/alerts`) — alerts as
  `{severity, title, detail, code, equipment_family}`; `code` must be in catalog.
- Map `ok → green`, `warning → yellow`, `critical → red`.

## Verification

- `GET /api/faults/catalog` lists the fixed codes + four categories.
- `GET /api/faults/status` returns `traffic` and a `families` tree.
- Saving an unknown `code` returns 400.

## Gotchas

Extending the catalog is a human PR (engine/skill maintenance), never a runtime
action.
