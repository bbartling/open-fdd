---
title: Security
parent: Operations
nav_order: 11
---

# Security

## Deployment posture

Open-FDD is **local-first** for LAN, VPN, or OT networks. Central binds the API on **:8080** and the `openfdd-ui` Caddy container serves the UI on **:3000**.

{: .warning }
Do not expose the central API directly on the public internet.

## Authentication

- JWT on protected REST routes
- Credentials in `workspace/auth.env.local` (mode `600`, never commit)
- Integrator role for commissioning; rotate with `openfdd_auth_init.sh`

## TLS

The `openfdd-ui` Caddy container terminates HTTP and proxies `/api` to central.
For HTTPS on the LAN edge, front the stack with a TLS reverse proxy (Caddy or
similar) or terminate TLS on your ingress. MQTT between fieldbus edges and
central is always MQTTS (8883) using the per-site provisioning kits.

## Secrets

- Never log or commit tokens, passwords, or `auth.env.local`
- MCP agents receive JWT via environment — not embedded in docs

## BACnet write safety

- `POST /api/bacnet/write-dry-run` before live writes
- Human approval required for production BACnet writes
- Agents must not write without explicit authorization

## Backup before change

Always back up `workspace/` before image updates or historian purges — see
[Backup, update, restore](backup-update-restore.html).

## Dependency scanning

Repository CI runs Rust audit, npm audit, Trivy, and Gitleaks on pull requests.
