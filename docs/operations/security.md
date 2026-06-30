---
title: Security
parent: Operations
nav_order: 11
---

# Security

## Deployment posture

Open-FDD is **local-first** for LAN, VPN, or OT networks. Default compose binds **127.0.0.1:8080**.

{: .warning }
Do not expose the bridge API directly on the public internet.

## Authentication

- JWT on protected REST routes
- Credentials in `workspace/auth.env.local` (mode `600`, never commit)
- Integrator role for commissioning; rotate with `openfdd_auth_init.sh`

## TLS

Use **Caddy** profiles (`caddy-http`, `caddy-tls`) or an external reverse proxy for HTTPS on the LAN edge.

Generate self-signed certs for lab TLS:

```bash
# See compose comments — openfdd-edge tls generate
docker compose -f docker/compose.edge.rust.yml --profile caddy-tls up -d
```

## Secrets

- Never log or commit tokens, passwords, or `auth.env.local`
- MCP agents receive JWT via environment — not embedded in docs

## BACnet write safety

- `POST /api/bacnet/write-dry-run` before live writes
- Human approval required for production BACnet writes
- Agents must not write without explicit authorization

## Backup before change

Always run `openfdd_rust_site_backup.sh` before image updates or historian purges.

## Dependency scanning

Repository CI runs Rust audit, npm audit, Trivy, and Gitleaks on pull requests.
