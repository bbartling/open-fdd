---
title: Provider point overlay (units, quantity, primary reference)
parent: Modeling
nav_order: 15
permalink: /modeling/provider-point-overlay.html
---

# Provider point overlay (units, quantity, primary reference)

Normal Framework inventory sync copies portal tags and sample units into the
committed site model. Some BACnet or hook points arrive with empty or unknown
units. Unit-dependent FDD and analytics (SV sweeps, OAT-METEO local reference,
VAV comfort bands, coverage cadence) need an explicit engineer declaration that
**survives the next inventory sync**.

## API

Operator or agent writes use `POST /api/model/point` with JWT and **`confirm: true`**
(viewers receive **403**). The MCP tool `openfdd_model_point_upsert` exposes the
same fields.

| Field | Purpose |
| --- | --- |
| `unit` | Declared unit code validated against `sql/contract/metric_units.json` |
| `quantity` | Engineering quantity kind when NF metadata is missing |
| `primary_reference` | When `true`, marks this binding as the site's primary reference for its SQL role (for example local outdoor air on `oa_t`) |

Other body fields (`building_id`, `equipment_id`, `point_id`, `role`, …) follow the
existing model-point contract. Writes are audited with the typed envelope and bump
the **model revision** hash used by analytics cache keys and FDD identity.

## Precedence

On each inventory sync:

1. **Engineer overlay** (`unit`, `quantity`, `primary_reference` from Open-FDD)
2. NF portal tag / unit metadata
3. Nothing — the point stays without a binding unit

An empty unit with no overlay makes unit-dependent rules **not assessed** (never a
silent default °F/°C guess). Incompatible units fail validation at write time.

## When to use

- After onboarding: list provider points with missing units and declare them before
  expecting SV-RANGE, sensor-health, or comfort analytics.
- When several points map to the same role (for example multiple `oa_t` candidates):
  mark exactly one `primary_reference: true` for OAT-METEO and BAS-vs-web logic.
  With none marked, the product uses the documented deterministic default (lowest
  committed binding id on weather or AHU equipment) and reports which point was chosen.

Implementation: `edge/src/csv_ingest/model_overlay.rs`, provider
`inventory_sync.rs` / `committed_model.rs`. Coverage cadence can also be bound
through the same overlay when NF metadata lacks `cadence_secs` (see
[`LOCAL_DEPLOYMENT.md`](../operations/LOCAL_DEPLOYMENT.md)).

## Related

- [`openfdd-nf-provider`](../../openfdd_agent_spec/skills/openfdd-nf-provider/SKILL.md) — site files and freshness
- [`ROLE_MAPPING_PARITY.md`](../migration/vibe19/ROLE_MAPPING_PARITY.md) — Haystack → SQL roles
- [`ANALYTICS_RESULT_CACHE.md`](../operations/ANALYTICS_RESULT_CACHE.md) — model revision in cache keys
