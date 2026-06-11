# `infra/` — edge orchestration and health checks

Open-FDD **application code** is built in GitHub Actions and published to **GHCR**. Edge hosts **pull containers**; Ansible does **not** deploy Python, React, FDD rules, or site models from a developer workstation.

## Architecture

```
GitHub (source) → Actions → ghcr.io/bbartling/openfdd-* → edge docker compose pull/up
                                                              ↓
                                                    Ansible: check / maintain / Caddy
```

| Path | Purpose |
|------|---------|
| **[ansible/](ansible/README.md)** | Inventory, `deploy.sh`, Docker compose template, health probes |
| **ansible/scripts/** | `post_deploy_check.sh`, `acme_operational_verify.sh`, `http_probes.py` |
## Deploy (any org, VPN/Tailscale)

```bash
cd infra/ansible
cp inventory.example.yml inventory.yml
cp secrets/acme.env.example secrets/acme.env.local   # chmod 600

set -a && source secrets/acme.env.local && set +a
OPENFDD_IMAGE_TAG=latest ../../scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
./deploy.sh check --limit acme_vm_bbartling
```

On the edge host directly:

```bash
OPENFDD_IMAGE_TAG=latest ~/open-fdd/scripts/update-open-fdd-edge.sh
```

## What Ansible still does

- `docker compose pull` / `up -d` / `ps`
- Host Caddy, FDD loop timers, bridge secrets template
- **Health checks** (API, dashboard, BACnet, MCP, logs) — read-only
- Optional **one-time** `-e openfdd_push_bacnet_config=true` for commission.env (prefer editing on edge)

## What Ansible does **not** do (use API instead)

| Data | Use |
|------|-----|
| BRICK model | `POST /api/model/commissioning-import` |
| FDD rules | `POST /api/rules/save` or `scripts/setup_gl36_fdd.py --host --token` |
| Commissioning CSV | BACnet discover on edge + model import |

## FDD tuning over VPN

1. `acme_operational_verify.sh` — stack stable  
2. `portfolio_collect.py` — central Dash history  
3. `GET /api/building-agent/tuning-brief` — tune bounds via API  

See [ansible/README.md](ansible/README.md).
