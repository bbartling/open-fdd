---
title: Acme live validation
parent: Operations
nav_order: 25
---

# Acme live validation

Acme (`vm-bbartling`) is the **live Open-FDD test site** on the OT LAN (reachable over Tailscale from the control machine). After every GHCR image update, run the read-only validation harness before closing a patch cycle.

## Recommended flow

```bash
export OPENFDD_IMAGE_TAG=v3.0.32

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
| `--full` | Quick + **all critical SPARQL presets**, **equipment rule kit zip** (live model discovery), chartable trend probe, **strict PyPI rule smoke**, local bundle validator |
| `--long` | Same depth as `--full` (reserved for extended soak hooks) |

`--strict-fdd` (default in `--full`) fails when `validate_acme_rules_pypi.py` errors. Use `--no-strict-fdd` to downgrade to WARN on live edge.

`--limit acme_vm_bbartling` also runs the SSH remote host probe (container tags, restarts, disk). Key-based SSH from bensserver is preferred; password fallback via `acme.env.local`.

## What counts as pass

- Bridge `/health` OK and reports expected `openfdd_version`
- Running GHCR image tag matches `OPENFDD_IMAGE_TAG` on **bridge and commission** (and optional services if running)
- Dashboard serves current `index-*.js` bundle (matches control machine build when available)
- **No duplicate BACnet device instances** in model (`duplicate_bacnet_device_instances == 0`)
- **No duplicate point IDs** in commissioning export
- Model equipment/point counts above profile thresholds (default ≥10 / ≥50)
- BACnet poll heartbeat recent; enabled point count above threshold
- Historian/trend API returns chartable data for a **real model point** (≥3 samples, not all-null)
- FDD rules saved and lint-clean; Building Status faults include equipment/point context (schema validated when no active faults)
- Rule Lab **equipment kit** zip includes manifest, rule sources, config, and result summary for equipment discovered from commissioning export (prefers AHU/VAV)
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

On failure, the console output lists suggested next steps (re-run full upgrade, check static bind mount).

### Report outputs

```bash
mkdir -p reports
export OPENFDD_IMAGE_TAG=3.0.33
./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full \
  --profile scripts/acme_validation_profile.example.json \
  --json-out reports/acme-live-validate.json \
  --junit-out reports/acme-live-validate.xml \
  --markdown-out reports/acme-live-validate.md
```

- **JSON** — machine-readable checks + redacted target metadata
- **JUnit XML** — CI gate (`failures` count)
- **Markdown** — human summary for patch-cycle notes

## Manual checklist after every GHCR update

```bash
export OPENFDD_IMAGE_TAG=<tag>   # SemVer without leading v, e.g. 3.0.33
./scripts/upgrade_edge_full.sh --limit acme_vm_bbartling
./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full \
  --profile scripts/acme_validation_profile.example.json
```

## Intentionally not tested

- BACnet writes / setpoint overrides
- Easy Pooge destructive reset (preview-only safety check runs)
- MCP/Ollama chat quality (disabled on Acme edge by design)
- Full OT BACnet Who-Is discovery (use `acme_operational_verify.sh` separately)
