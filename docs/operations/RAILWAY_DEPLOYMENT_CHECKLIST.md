---
title: Railway deployment checklist
parent: Railway deployment
nav_order: 1
---

# Railway deployment checklist (open-fdd)

Use with [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md). Prefer GHCR `:sha-<7>` for controlled tests; `:nightly` for the floating channel after a green master publish.

## Pre-deployment

- [ ] GHCR packages pull without login (or Railway has read-only GHCR credentials)
- [ ] Railway project created
- [ ] Decide `:nightly` vs `:sha-<7>`
- [ ] Know whether this is **CSV-only** or **cloud MQTTS hub** (central + web + mqtt; fieldbus on-prem)

## Step 1 — Deploy `openfdd-central` first

- [ ] Image `ghcr.io/bbartling/openfdd-central:nightly` (or sha pin)
- [ ] Volume on `/workspace` (≥5GB)
- [ ] Vars: `OPENFDD_JWT_SECRET` (≥32 chars), `OPENFDD_ADMIN_PASSWORD`, **`OPENFDD_AGENT_PASSWORD`** (FDD AI / MCP — distinct from admin), `OPENFDD_WORKSPACE=/workspace`, `OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet`, `OPENFDD_REACT_UI=1`
- [ ] For MQTTS hub also set MQTT client env expected by Central (see main Railway guide)
- [ ] Deploy and wait until `GET /api/health` returns 200
- [ ] From Railway shell: `getent hosts openfdd-central.railway.internal` and `curl -fsS http://openfdd-central.railway.internal:8080/api/health`

## Step 2 — Deploy `openfdd-mqtt` when using cloud MQTTS (default hub)

Cloud MQTTS is the point of the hub: on-prem fieldbus publishes into Railway MQTTS; Central ingests. Do **not** treat MQTT as an afterthought for OT/live sites.

- [ ] Image `ghcr.io/bbartling/openfdd-mqtt:nightly`
- [ ] Private networking only (do not expose 8883 publicly without a deliberate TLS/ACL design)
- [ ] Provision / mount broker certs + ACL as required by the mqtt image docs
- [ ] Confirm broker listens on **8883** MQTTS inside the private network

## Step 3 — Deploy `openfdd-web` after central is healthy

- [ ] Image `ghcr.io/bbartling/openfdd-web:nightly`
- [ ] `OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080` (no `http://`)
- [ ] Optional: `OPENFDD_NGINX_RESOLVER=auto` (default) or pin a nameserver from `/etc/resolv.conf`
- [ ] Public domain on **web only**
- [ ] Healthcheck path `/` (SPA) or prefer verifying `/api/health` via the web proxy after boot
- [ ] If older images fail with `host not found in upstream`: central DNS race — ensure central is healthy, then redeploy web on a tip image with lazy DNS (variable upstream + resolver)

## Step 4 — Verify

- [ ] `curl -fsS https://<public-web>/api/health`
- [ ] Browser login with **admin** password (not agent)
- [ ] `GET /api/auth/status` shows `auth_required: true` and `agent_login_configured: true`
- [ ] Agent JWT: `POST /api/auth/login` as `agent` **or** admin `POST /api/auth/agent-token` → use as `OPENFDD_MCP_TOKEN` only on private MCP
- [ ] Never commit JWTs / agent password; rotate after demos
- [ ] Sidebar shows `3.3.N+shortsha`
- [ ] CSV lab: import `openfdd_package_v1`
- [ ] MQTTS hub: fieldbus (on-prem) connected to Railway MQTTS; Operations MQTT monitor shows traffic
- [ ] Optional: Operations → MQTT → **Download edge kit** (operator/admin); mount ZIP at `/mqtt` on-prem (never ships CA private key)

## Fieldbus stays on-prem

- [ ] Do **not** expect BACnet broadcast discovery on Railway
- [ ] Run `openfdd-fieldbus` on the OT LAN / VPN and point MQTTS at the cloud broker
