---
title: Security
parent: Operations
nav_order: 11
---

# Security

## Deployment posture

Open-FDD is **local-first** for LAN, VPN, or OT networks. Central binds the API on **:8080** and the `openfdd-web` React container serves the engineering UI on **:3000**.

{: .warning }
Do not expose the central API directly on the public internet.

## Caddy edge (optional)

Optional compose overlay `docker/compose.caddy.yml` puts **Caddy on :80** so
`http://<machine-ip>/` serves the React SPA (and `/api*` → central). Enable with:

```bash
OPENFDD_CADDY=1 ./scripts/openfdd_stack_up.sh standalone
# or: docker compose -f docker/compose.standalone.yml -f docker/compose.caddy.yml up -d
```

Security defaults in the Caddyfiles: admin API off, security headers, probe-path
404s, `no-new-privileges`, dropped capabilities. When Caddy fronts the LAN, bind
central to loopback: `OPENFDD_CENTRAL_BIND=127.0.0.1`. Use
`docker/caddy/Caddyfile.tls` (+ certs) for HTTPS / HSTS.

## Authentication

- JWT on protected REST routes
- Credentials in `workspace/auth.env.local` (mode `600`, never commit)
- Integrator role for commissioning; rotate with `openfdd_auth_init.sh`

## TLS

The `openfdd-web` React app talks to central’s REST API (`:8080`). For HTTPS
on the LAN edge, use the Caddy TLS Caddyfile (above) or terminate TLS on your
ingress. MQTT between fieldbus edges and central is always MQTTS (8883) using
the per-site provisioning kits.

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
