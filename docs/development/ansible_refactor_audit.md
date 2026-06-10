---
title: Ansible refactor audit
nav_exclude: true
---

# Open-FDD Ansible refactor audit (2026-06-09)

## 1. Inventory

| File | Purpose | Status |
|------|---------|--------|
| `deploy.sh` | CLI entry | **Modified** — GHCR-first commands only |
| `deploy_docker.yml` | Compose pull/up | **Modified** — removed rsync, gated site pack |
| `edge_operational_sync.yml` | docker + API health | **Keep** |
| `edge_docker_maintenance.yml` | Prune | **Keep** |
| `post_deploy_check.yml` | Probes | **Keep** |
| `ollama_bootstrap.yml` | Host Ollama install | **Keep** (optional) |
| `edge_ai_stack.yml` | MCP systemd | **Keep** (legacy path) |
| `os_update.yml` | apt upgrade | **Keep** |
| `deploy.yml` | Full rsync stack | **Moved → legacy/** |
| `bench_edge_data_sync.yml` | Bench data copy | **Moved → legacy/** |
| `scripts/post_deploy_check.sh` | HTTP probes | **Keep** |
| `scripts/acme_operational_verify.sh` | Acme smoke | **Keep** |
| `scripts/http_probes.py` | Probe library | **Keep** |
| `Makefile` | Shortcuts | **Modified** — docker/check only |
| `upgrade_edge_ghcr.sh` | Image-only upgrade | **Keep** (primary) |
| `update-open-fdd-edge.sh` | On-host pull/up | **New** |

## 2. Legacy file deployment removed

| Pattern | Location | Action |
|---------|----------|--------|
| `ansible.builtin.synchronize` | `deploy_docker.yml` | **Removed** (was `workspace/api` rsync) |
| `workspace/api` bind mount | `docker-compose.edge.yml.j2` | **Removed** — image is source of truth |
| `ansible.builtin.copy` open_fdd/api | `legacy/deploy.yml` | **Isolated** |
| workspace data tar sync | `deploy_docker.yml` | **Default off** (`openfdd_docker_sync_workspace_data: false`) |
| model/rules/points push | `deploy_docker.yml` | **Gated** (`openfdd_push_site_pack: false`) |

Health-related `copy`/`template` retained: `bridge.secret.env`, optional `auth.env.local` bootstrap.

## 3. Deployment flow

### Before

```
bensserver → rsync workspace/api → edge mount overrides GHCR image
          → tar sync workspace/data
          → copy model.json / rules_store from edge_backup
          → slow Tailscale SCP
```

### After

```
GitHub Actions → GHCR :latest
bensserver → ansible: docker compose pull && up -d
          → check (HTTP probes only)
edge     → update-open-fdd-edge.sh (optional, no Ansible)
models/rules → HTTPS API over VPN
```

## 4. Remaining Ansible responsibilities

- Install/configure Docker, Caddy, systemd timers on edge host
- Render `docker-compose.yml` from template
- `docker compose pull` / `up -d`
- Post-deploy health validation (retries in `http_probes.py`)
- Optional OS updates and disk maintenance

## 5. Proof: no normal deploy path syncs app source

- `deploy.sh docker` → `deploy_docker.yml` — no `synchronize`, no `workspace/api` mount
- `upgrade_edge_ghcr.sh` sets `openfdd_docker_sync_workspace_data=false`
- Default `openfdd_push_site_pack: false` in `group_vars/pi_bcn.yml`

## 6. Future rule distribution

Use `POST /api/rules/save`, `POST /api/model/commissioning-import`, `setup_gl36_fdd.py --host --token`. Ansible file transport for rules/models is **deprecated**.

## 7. `.cursor/` gitignore

Added `.cursor/` to root `.gitignore`; removed from index with `git rm -r --cached .cursor` (local files preserved).
