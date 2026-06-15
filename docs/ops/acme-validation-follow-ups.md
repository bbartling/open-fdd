---
title: ACME validation follow-ups
parent: Operations
nav_exclude: true
---

# ACME validation follow-ups

Tracked work after the overnight FDD validation PR (`harden/acme-overnight-fdd-validation`).

## 1. FDD run-history equipment grouping

**Problem:** Live alert enrichment populates `model_context.equipment`, but batch FDD run history rows often have `equipment: null` / missing `equipment_names`.

**Goal:** Populate equipment identity on persisted run rows when inferable (title prefix, fault code, flagged columns) so Central and RCx reports can group historical faults by equipment.

**Acceptance criteria:**

- Batch FDD run rows include `equipment_names` or equivalent when inferable.
- Historical fault summaries group by equipment without re-parsing titles client-side.
- Missing equipment is explicit in the API, not silent `null`.
- Tests cover run rows that currently return `equipment: null`.

**Suggested files:** `workspace/api/openfdd_bridge/fdd_results.py`, `validate_fdd_run_schema()` in `acme_fdd_audit.py`.

## 2. RTU normalized role mapping

**Problem:** `acme-vm-bbartling-rtu-01` is flagged as missing some normalized AHU roles (`supply_fan_command`, etc.) in `equipment_point_role_audit()`.

**Goal:** Decide whether RTU maps to AHU-like roles, RTU-specific roles, or partial-equipment warnings only.

**Acceptance criteria:**

- RTU missing roles reported clearly (informational unless blocking).
- RTU gaps do not fail VAV/AHU duplicate or BACnet health checks.
- Role expectations distinguish AHU, VAV, RTU, and building-level equipment.

**Suggested files:** `acme_fdd_audit.py` (`AHU_POINT_ROLES`, `_equipment_type()`), site commissioning model.

## 3. True overnight validation (post-3.0.33 deploy)

**Problem:** Try-out validation used `ACME_CYCLE_SLEEP_MINUTES=0` (~2 minutes total), not wall-clock 2-hour spacing.

**Goal:** After bridge image **3.0.33+** is deployed to ACME, run read-only overnight cycles with real spacing.

**Acceptance criteria:**

- At least 4 cycles with `ACME_CYCLE_SLEEP_MINUTES=120`.
- Live bridge reports deployed tag (e.g. `3.0.33`).
- `building_status_context` passes on live bridge (not deferred).
- BACnet freshness, duplicate checks, and equipment context remain healthy.
- Reports under `reports/acme_overnight_logs/` document actual timestamps.

**Command:**

```bash
OPENFDD_LIVE_ACME=1 OPENFDD_IMAGE_TAG=3.0.33 ACME_OVERNIGHT_CYCLES=4 \
  ACME_WINDOW_HOURS=2 ACME_CYCLE_SLEEP_MINUTES=120 \
  python3 scripts/acme_overnight_fdd_validate.py --limit acme_vm_bbartling
```
