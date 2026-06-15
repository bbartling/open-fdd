---
title: ACME deploy 3.0.33 validation plan
parent: Operations
nav_exclude: true
---

# ACME deploy 3.0.33 validation plan

**Do not run automatically.** Use after the overnight FDD validation PR is merged and a new GHCR tag is published.

## What this deploy fixes

Live ACME on bridge **3.0.32** still returns FDD alerts with empty `model_context.equipment.name`. The branch fix in `fault_model_context.py` parses GL36-style titles (`AHU-C · AHU SAT flatline 1h`) and fault codes to populate equipment name/type. **The running bridge is not fixed until a new image is deployed.**

Local/tests and the overnight runner’s **post-enrich** checks pass; live `building_status_context` fails on 3.0.32 by design until deploy.

## Prerequisites

1. PR merged: *Harden ACME live-site FDD validation and VAV AHU rule coverage*
2. CI published GHCR tag `3.0.33` (no leading `v`)
3. Operator approval for live edge upgrade (read-only validation only; no BACnet writes)

## Deploy sequence

```bash
export OPENFDD_IMAGE_TAG=3.0.33

# Full upgrade: UI static + GHCR containers
./scripts/upgrade_edge_full.sh --limit acme_vm_bbartling

# Confirm live bridge version/tag
# GET /health → openfdd_version
# GET /health/stack → image_tag
```

## Post-deploy read-only validation

### Quick harness

```bash
OPENFDD_IMAGE_TAG=3.0.33 ./scripts/acme_post_deploy_validate.sh \
  --limit acme_vm_bbartling --full \
  --profile scripts/acme_validation_profile.example.json
```

**Expected:** `building_status_context` **pass** — FDD alerts include non-empty `model_context.equipment.name` (e.g. `AHU-C`, `VAV-E`).

### Overnight try-out (4 cycles, no wall-clock sleep)

```bash
OPENFDD_LIVE_ACME=1 OPENFDD_IMAGE_TAG=3.0.33 ACME_OVERNIGHT_CYCLES=4 \
  ACME_WINDOW_HOURS=2 ACME_CYCLE_SLEEP_MINUTES=0 \
  python3 scripts/acme_overnight_fdd_validate.py --limit acme_vm_bbartling
```

**Expected:** 4/4 pass; `schema_errors_live_bridge` empty; harness not deferred.

### True overnight (optional)

```bash
OPENFDD_LIVE_ACME=1 OPENFDD_IMAGE_TAG=3.0.33 ACME_OVERNIGHT_CYCLES=4 \
  ACME_WINDOW_HOURS=2 ACME_CYCLE_SLEEP_MINUTES=120 \
  python3 scripts/acme_overnight_fdd_validate.py --limit acme_vm_bbartling
```

Reports: `reports/acme_overnight_fdd_validation.md` (gitignored).

## Safety

All validation is **read-only**. No BACnet writes, commands, overrides, schedules, or setpoint changes.
