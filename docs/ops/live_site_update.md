---
title: Live site update
parent: Operations
nav_order: 1
---

# Live site update

Upgrade GHCR images on a **live edge host** that already has `~/open-fdd/` — no `git pull` on the host.

{: .note }
> **IT operators:** prefer [Quick Start — Updating the stack]({% link quick-start/updating.md %}) and `openfdd_site_backup.sh` / `openfdd_site_update.sh` on the edge host. This page adds control-machine UI deploy and Ansible paths.

## Layout on the edge host

```text
~/open-fdd/
  docker-compose.yml
  workspace/          # site state — backup first
```

`workspace/` holds BACnet commissioning, poll CSV, feather historian, BRICK model, FDD rules, and `auth.env.local`. Image upgrades must **preserve** it.

See [Backup and restore]({% link ops/backup-restore.md %}) before any upgrade.

## Concepts

| Term | Meaning |
|------|---------|
| **Container** | Running instance (`bridge`, `commission`, `mcp-rag`) — recreated on upgrade |
| **Image** | GHCR package (tag `latest` or dated tag) |
| **`workspace/`** | Open-FDD site state on disk — **do not delete** |

## 1. Verify new images on GHCR

Three images must exist for every tag:

```bash
export NEW_TAG="${NEW_TAG:-latest}"

docker manifest inspect ghcr.io/bbartling/openfdd-bridge:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-commission:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG} >/dev/null &&
echo "All three images exist for ${NEW_TAG}"
```

## 2. Update dashboard UI (when release changed React)

{: .warning }
> **Image pull alone does not update the browser UI.** The Operator Bridge serves `workspace/api/static/app/` from the bind mount **before** image-baked assets.

**From control machine (full repo):**

```bash
cd /path/to/open-fdd
./scripts/build_operator_dashboard.sh prod
cd infra/ansible
RUN_POST_CHECK=0 ./deploy.sh ui --limit <inventory_host>
```

Confirm hash on edge:

```bash
curl -sf http://<edge-ip>/ | grep -o 'index-[^"]*\.js' | head -1
```

**One command (UI + images + insurance check):**

```bash
OPENFDD_IMAGE_TAG=latest ./scripts/upgrade_edge_full.sh --limit <inventory_host>
```

## 3. Pull and recreate (edge host)

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
./scripts/openfdd_site_update.sh
```

Manual equivalent:

```bash
cd ~/open-fdd
docker compose pull
docker compose up -d --force-recreate
docker compose ps
curl -sf http://127.0.0.1:8765/health
```

## 4. Ansible image-only (control machine)

```bash
OPENFDD_IMAGE_TAG=latest RUN_POST_CHECK=1 ./scripts/upgrade_edge_ghcr.sh --limit <inventory_host>
```

## 5. Validate

→ [Deployment validation]({% link ops/deployment-validation.md %})

## Rollback

Restore `docker-compose.yml` from backup, pull previous tag, `docker compose up -d --force-recreate`. `workspace/` is unchanged. Details: [Backup and restore]({% link ops/backup-restore.md %}).

## Related

- [Updating the stack]({% link quick-start/updating.md %}) — edge-host helper scripts
- [Containers]({% link architecture/containers.md %}) — three-image architecture
