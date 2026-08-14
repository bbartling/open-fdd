---
title: Security
parent: Operations
nav_order: 11
---

# Security

## Deployment posture

Open-FDD is **local-first** for LAN, VPN, or OT networks. Central binds the API on **:8080** and the `openfdd-web` React container serves the engineering UI on **:3000**.

{: .warning }
Open-FDD is **not internet-ready**. LAN / VPN / OT only until the checklist below is complete **and** independently reviewed.

## Not internet-ready until

- [x] Fail-closed when Central binds non-loopback without a ≥32-char `OPENFDD_JWT_SECRET` and `OPENFDD_ADMIN_PASSWORD`
- [x] Open mode (unset JWT secret) is loopback-only
- [x] Startup logs `auth_enabled` **without** secrets
- [ ] Dedicated reverse proxy / TLS on every deployment (expose **web proxy only**; do not publish `:8080` to the internet)
- [ ] Per-building tenancy (JWT role is **not** multi-tenant isolation)
- [x] Viewer is read-only; mutations require operator/admin
- [x] Login throttle + generic credential errors
- [x] Package zip-slip / bomb caps on archive ingest
- [x] No wildcard CORS in the SPA nginx config
- [x] SPA CSP without `unsafe-eval` (Unity `/twins` may use `wasm-unsafe-eval` only)
- [ ] Production secret rotation, SSO, and WAF as required by the site

OT writes stay **off** unless an operator explicitly enables them.

## Deployment posture

## Caddy edge (optional)

Optional compose overlay `docker/compose.caddy.react.yml` puts **Caddy on :80** so
`http://<machine-ip>/` serves the React SPA (and `/api*` → central). Enable with
react / react-ot / csv recipes (default ON for react/react-ot):

```bash
OPENFDD_CADDY=1 ./scripts/openfdd_stack_up.sh react
# or: docker compose -f docker/compose.react.yml -f docker/compose.caddy.react.yml up -d
```

Security defaults in the Caddyfiles: admin API off, security headers, probe-path
404s, `no-new-privileges`, dropped capabilities. When Caddy fronts the LAN, bind
central to loopback: `OPENFDD_CENTRAL_BIND=127.0.0.1`. Use a TLS Caddyfile (+ certs)
for HTTPS / HSTS when you terminate TLS at the edge.

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
