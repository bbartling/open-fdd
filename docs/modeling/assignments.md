---
title: Assignments
parent: Haystack Modeling
nav_order: 2
---

# Assignments

Assignments connect **driver points** → **Haystack point IDs** → **FDD/CDL rules**. This is the binding layer integrators configure before SQL rules return meaningful faults.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/assignments` | Current assignment graph |
| POST | `/api/model/assignments/save` | Persist assignments |
| POST | `/api/model/assignments/resolve` | Resolve refs |
| GET | `/api/model/algorithm-bindings` | CDL algorithm bindings |

## FDD wires

Visual assignment proposals:

- `POST /api/fdd-wires/propose-assignments`
- `POST /api/fdd-wires/sync-from-assignments`

## Agent rule

Per project convention: bind drivers → Haystack IDs → FDD/CDL via `/api/model/assignments` before activating SQL rules.

## Dashboard

**Model** tab → **FDD mapping** sub-tab — map Haystack points to FDD rule inputs.
