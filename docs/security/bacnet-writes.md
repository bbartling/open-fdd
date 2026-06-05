---
title: BACnet write allowlists
parent: Security
nav_order: 3
---

# BACnet write allowlists

Supervisory writes require:

1. **Feature flag** enabled in environment (off by default).
2. **Allowlist** of device instance + object type/instance.
3. **Commission** role on API calls.
4. **Audit** log review after commissioning sessions.

See operator guide: [BACnet write safety](../bacnet/write-safety).

Never enable blanket write access for agent or integrator automation without human approval per site.
