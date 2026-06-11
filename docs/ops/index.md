---
title: Operations
nav_order: 8
has_children: true
---

# Operations

Runbooks for live edge hosts after the initial [Quick Start]({% link quick-start/index.md %}) deploy.

| Page | When to use |
|------|-------------|
| [Live site update]({% link ops/live_site_update.md %}) | Pull new GHCR tags, preserve `workspace/` |
| [Backup and restore]({% link ops/backup-restore.md %}) | Archive `workspace/` before upgrades |
| [Logging and audit]({% link ops/logging.md %}) | Auth audit trail, rotation, Docker log caps |
| [Deployment validation]({% link ops/deployment-validation.md %}) | Post-upgrade smoke and insurance checks |

Site-specific lab notes (example BACnet scope, GL36 rules): [Examples & lab notes]({% link examples/index.md %}).

For first-time deploy: [Quick Start — Docker]({% link quick-start/docker.md %}).
