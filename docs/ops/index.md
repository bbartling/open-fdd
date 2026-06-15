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
| [ACME live validation]({{ "/operations/acme-live-validation/" | relative_url }}) | Live BACnet HVAC site — read-only harness |
| [Bench 5007 long FDD smoke]({{ "/operations/bench-5007-long-fdd-smoke/" | relative_url }}) | Dual-source BACnet/Niagara validation |
| [Bench 5007 dual-source smoke]({{ "/operations/bench-5007-dual-source-smoke/" | relative_url }}) | Shorter bench equivalence check |

Site-specific lab notes (example BACnet scope, GL36 rules): [Examples & lab notes]({{ "/examples/" | relative_url }}).

For first-time deploy: [Quick Start — Docker]({{ "/quick-start/docker/" | relative_url }}).
