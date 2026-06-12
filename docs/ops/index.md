---
title: Operations
nav_order: 8
has_children: true
---

# Operations

Runbooks for live edge hosts after the initial [Quick Start]({{ "/quick-start/" | relative_url }}) deploy.

| Page | When to use |
|------|-------------|
| [Live site update]({{ "/ops/live_site_update/" | relative_url }}) | Pull new GHCR tags, preserve `workspace/` |
| [Backup and restore]({{ "/ops/backup-restore/" | relative_url }}) | Archive `workspace/` before upgrades |
| [Logging and audit]({{ "/ops/logging/" | relative_url }}) | Auth audit trail, rotation, Docker log caps |
| [Deployment validation]({{ "/ops/deployment-validation/" | relative_url }}) | Post-upgrade smoke and insurance checks |
| [Acme live validation]({{ "/ops/acme-live-validation/" | relative_url }}) | Read-only harness after GHCR upgrades |
| [Acme deploy 3.0.33 plan]({{ "/ops/acme-deploy-3.0.33-validation/" | relative_url }}) | Post-merge deploy and re-validation |
| [Acme validation follow-ups]({{ "/ops/acme-validation-follow-ups/" | relative_url }}) | Run-history equipment, RTU roles, true overnight |

Site-specific lab notes (example BACnet scope, GL36 rules): [Examples & lab notes]({{ "/examples/" | relative_url }}).

For first-time deploy: [Quick Start — Docker]({{ "/quick-start/docker/" | relative_url }}).
