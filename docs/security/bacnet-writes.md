---
title: BACnet write allowlists
parent: Security
nav_order: 6
---

# BACnet write allowlists

Supervisory writes require:

1. **Feature flag** enabled in environment (off by default).
2. **Allowlist** file at `workspace/bacnet/write_allowlist.json` (copy from [`write_allowlist.example.json`](write_allowlist.example.json)). If the flag is on but the allowlist is missing, writes are **denied**.
3. **Integrator** role on API calls.
4. **Audit** log review after commissioning sessions.

Allowlist entries support `device_instance`, `object_identifier`, `property_identifier`, optional `priority_min`/`priority_max`, `value_min`/`value_max`, and `allowed_values` for binary/multistate targets.

Lab-only override: `OFDD_BACNET_WRITE_ALLOW_ANY=1` (audited; not for production edges).

See operator guide: [BACnet write safety](../bacnet/write-safety).

Never enable blanket write access for agent or integrator automation without human approval per site.
