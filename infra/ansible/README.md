# Ansible edge orchestration (Open-FDD)

**Open-FDD deployment is container-based. Ansible does not deploy application files. Ansible only orchestrates updates and validates system health.**

## Quick start

```bash
cd infra/ansible
cp inventory.example.yml inventory.yml
cp host_vars/acme_vm_bbartling.yml.example host_vars/acme_vm_bbartling.yml
cp secrets/acme.env.example secrets/acme.env.local

set -a && source secrets/acme.env.local && set +a
OPENFDD_IMAGE_TAG=latest ./deploy.sh docker --limit acme_vm_bbartling
./deploy.sh check --limit acme_vm_bbartling
```

Or from repo root:

```bash
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
```

## Commands

| Command | Purpose |
|---------|---------|
| **`docker`** | GHCR pull + `docker compose up -d` + timers (primary) |
| **`check`** | Health probes only — no file changes |
| **`maintain`** | Safe `docker system prune` on edge |
| **`ops`** | docker + maintenance + API TTL sync probe |
| **`os`** | apt upgrade on edge host |
| **`help`** | Full usage |

```bash
./deploy.sh help
make docker HOST=acme_vm_bbartling
```

## Remote validation (Tailscale / VPN)

Any integrator with SSH + secrets can run:

```bash
./scripts/acme_operational_verify.sh --host "$ACME_SSH_HOST"
./scripts/post_deploy_check.sh --limit acme_vm_bbartling --full
```

FDD rules and models are pushed over **HTTPS** (`setup_gl36_fdd.py --host --token`), not Ansible copy.

## Docker stack on edge

| Service | Image |
|---------|--------|
| bridge | `ghcr.io/bbartling/openfdd-bridge:latest` |
| commission | `ghcr.io/bbartling/openfdd-commission:latest` |
| mcp-rag | `ghcr.io/bbartling/openfdd-mcp-rag:latest` |
| ollama | `ollama/ollama` (optional, in compose when `enable_ollama: true`) |

Runtime bind mount: `~/open-fdd/workspace` (feather, auth env, BACnet CSVs on edge). **No** `workspace/api` override — app code is inside the image.

## Deprecated

- `all`, `ui`, `backend`, `drivers`, `data` → moved to [legacy/README.md](legacy/README.md)
- `-e openfdd_push_site_pack=true` → one-time bootstrap only; use API thereafter
- Workstation rsync / `make ui-deploy` → removed from Makefile

## Acme (`acme_vm_bbartling`)

| Device range | Notes |
|--------------|--------|
| JCI VAV 1–100 | Imperial °F |
| AHU 1100, boiler 1002 | Plant |
| Trane VAV 11000–13000 | Metric °C → `device_poll_profiles.csv` on edge |

```bash
./scripts/acme_operational_verify.sh --host "$ACME_SSH_HOST"
```

## Secrets

[secrets/README.md](secrets/README.md) — never commit `*.env.local` or real inventory IPs.
