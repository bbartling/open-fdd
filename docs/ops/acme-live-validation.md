---
title: Acme live validation
parent: Operations
nav_order: 25
---

# Acme live validation

Acme (`vm-bbartling`) is the **live Open-FDD test site** on the OT LAN (reachable over Tailscale from the control machine). After every GHCR image update, run the read-only validation harness before closing a patch cycle.

## Recommended flow

```bash
export OPENFDD_IMAGE_TAG=3.0.32

# Full upgrade: React static bundle + GHCR containers (not image-only)
./scripts/upgrade_edge_full.sh --limit acme_vm_bbartling

# Rigorous live validation
./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full \
  --json-out reports/acme-live-validate.json
```

Use **`upgrade_edge_full.sh`**, not `upgrade_edge_ghcr.sh` alone, when the Operator Bridge UI changed — the edge bind-mount serves `workspace/api/static/app/` **before** image-baked assets (`edge_sync_ui_static.sh` rsyncs the bundle; `deploy.sh ui` was removed).

GHCR SemVer tags omit the leading `v` (`3.0.32`, not `v3.0.32`). `upgrade_edge_ghcr.sh` normalizes `OPENFDD_IMAGE_TAG` automatically.

## Modes

| Flag | What runs |
|------|-----------|
| `--quick` | Health, auth, UI bundle, Docker tag, model health, **duplicate device/point checks**, BACnet poll, trends, FDD summary |
| `--full` | Quick + SPARQL presets, Rule Lab export, local bundle/PyPI rule smoke, `stack_health_check.sh` |
| `--long` | Same depth as `--full` (reserved for extended soak hooks) |

## What counts as pass

- Bridge `/health` OK and reports expected `openfdd_version`
- Running GHCR image tag matches `OPENFDD_IMAGE_TAG` (when set)
- Dashboard serves current `index-*.js` bundle (matches control machine build when available)
- **No duplicate BACnet device instances** in model (`duplicate_bacnet_device_instances == 0`)
- **No duplicate point IDs** in commissioning export
- Model equipment/point counts above profile thresholds (default ≥10 / ≥50)
- BACnet poll heartbeat recent; enabled point count above threshold
- Historian/trend API returns chartable data (or explicit warm-up warning)
- FDD rules saved and lint-clean; Building Status faults include equipment/point context
- Recent ops logs free of `Traceback` / fatal import errors
- Host disk/memory within thresholds (when Ansible remote probe succeeds)

Warnings (e.g. MCP/Ollama disabled, single stale BACnet point) do not fail the run unless paired with hard errors.

## Configuration (no secrets in git)

Copy and customize locally:

```bash
cp scripts/acme_validation_profile.example.json scripts/acme_validation_profile.local.json
```

Point the harness at it:

```bash
./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full \
  --profile scripts/acme_validation_profile.local.json
```

Credentials load from gitignored files only:

- `workspace/auth.env.local`
- `infra/ansible/secrets/acme.env.local`

Quote passwords that contain `$` or `&` in `auth.env.local`.

## Optional live pytest

```bash
ACME_VALIDATE_LIVE=1 python -m pytest tests/live/test_acme_live.py -q
```

Requires Tailscale/inventory reachability and local secrets. CI skips this test by default.

## Overnight FDD validation (read-only)

Four-cycle runner for BACnet health, duplicate audit, equipment roles, and FDD fault schema. **Requires explicit opt-in:**

```bash
OPENFDD_LIVE_ACME=1 OPENFDD_IMAGE_TAG=3.0.32 ACME_OVERNIGHT_CYCLES=4 \
  ACME_WINDOW_HOURS=2 ACME_CYCLE_SLEEP_MINUTES=0 \
  python3 scripts/acme_overnight_fdd_validate.py --limit acme_vm_bbartling
```

| Variable | Default | Notes |
|----------|---------|-------|
| `OPENFDD_LIVE_ACME` | (unset) | Must be `1` for live API calls |
| `ACME_OVERNIGHT_CYCLES` | `4` | Number of validation cycles |
| `ACME_WINDOW_HOURS` | `2` | Historian lookback per cycle |
| `ACME_CYCLE_SLEEP_MINUTES` | `0` | Set `120` for true 2-hour wall-clock spacing |

Reports are written under `reports/` (gitignored). See [ACME validation follow-ups]({% link ops/acme-validation-follow-ups.md %}) and [ACME deploy 3.0.33 validation plan]({% link ops/acme-deploy-3.0.33-validation.md %}).

### Live bridge vs branch fix

Live ACME on **3.0.32** may fail `building_status_context` because the deployed bridge does not yet include `fault_model_context` equipment enrichment. The branch fix enriches payloads correctly in tests and via the overnight runner’s post-enrich check. **Do not claim live ACME is fixed until a new image (e.g. 3.0.33) is published and deployed**, then re-run validation.

## Safety

Normal validation is **read-only**. It does not:

- Reset BACnet, model, rules, or historian data
- Run Easy Pooge or bench resets
- Write setpoints or BACnet values
- Start packet captures

Destructive actions require explicit operator tooling outside this harness.

## Reports

JSON reports redact tokens and private hostnames. Example fields:

- `summary.ok`, `summary.failed`, `summary.warnings`
- `checks[].id`, `checks[].category`, `checks[].status`, `checks[].message`

On failure, the console output lists suggested next steps (re-run full upgrade, check static bind mount, run `stack_health_check.sh`).
