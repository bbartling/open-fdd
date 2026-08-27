---
title: Railway deployment checklist
parent: Railway deployment
nav_order: 1
---

# Railway deployment checklist (open-fdd)

Use with [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) and [external agents](../examples/external-agents.md). Prefer GHCR `:sha-<7>` for controlled tests; `:nightly` after a green master publish.

> **Experimental cloud lab** — LAN/VPN-first product. This checklist is for labs/demos, not a public-internet hardening claim.

---

## AI / Railway-assistant bootstrap context (paste this)

**Audience:** Railway AI, Cursor, or any agent standing up Open-FDD from GHCR.  
**Not in scope for Railway AI:** Open-FDD MCP, AFDD SQL, BACnet/Modbus, HVAC FDD. Those are done by a **local external AI** after deploy, using JWT auth to private central.

### Default topology (assume this unless the human says CSV-only)

Deploy **three** Railway services from GHCR, in order:

| Order | Service | Image | Exposure | Purpose |
|------:|---------|-------|----------|---------|
| 1 | `openfdd-central` | `ghcr.io/bbartling/openfdd-central:nightly` (or `:sha-<7>`) | **Private** | JWT API, Parquet historian, DataFusion FDD, MQTTS ingest client |
| 2 | `openfdd-mqtt` | `ghcr.io/bbartling/openfdd-mqtt:nightly` | **Private** MQTTS `:8883` | Cloud broker hub — **default for live OT** |
| 3 | `openfdd-web` | `ghcr.io/bbartling/openfdd-web:nightly` | **Public** HTTP | React SPA only |

**Do not deploy `openfdd-fieldbus` on Railway.** Fieldbus stays on-prem (OT LAN / VPN) and publishes MQTTS into the cloud broker. BACnet broadcast discovery does not work in Railway.

**CSV-only lab exception:** omit `openfdd-mqtt` only when the human explicitly wants package/CSV import with no live edges. Live OT / multi-building always includes MQTT.

### What Railway AI should configure

1. Create project; pull public GHCR (or registry credentials if packages are private).
2. Attach durable volume to central at `/workspace` (≥5 GB).
3. Generate secrets (never commit, never paste into chat logs):
   - `OPENFDD_JWT_SECRET` (≥32 random chars)
   - `OPENFDD_ADMIN_PASSWORD` — **human browser UI only**
   - `OPENFDD_AGENT_PASSWORD` — **external FDD AI / MCP only** (distinct from admin)
4. Prefer historian via `OPENFDD_STORAGE_URL=file:///workspace/openfdd` (or Railway bucket `s3://…` per [historian-s3.md](historian-s3.md)). `OPENFDD_PARQUET_ROOT` is a legacy alias — avoid for new deploys.
5. Set `OPENFDD_WORKSPACE=/workspace`, `OPENFDD_REACT_UI=1`, `OPENFDD_UI_GENERATION_DEFAULT=react`.
6. Deploy **central → wait `/api/health` 200 → mqtt → web**.
7. Web: `OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080` (host:port only, no `http://`).
8. Keep central + mqtt **private**; public domain on **web only**.
9. Wire central’s MQTT client env to the private broker (host/port/certs) — see main Railway guide; never commit certs.
10. Tell the human: FDD assistance = local Cursor/Claude/Codex + `agent` JWT; Railway AI does **not** run `openfdd-mcp`.
11. **App updates must not wipe telemetry:** keep the same `/workspace` volume (or same `s3://` bucket). Only replace GHCR image tags. Canonical Parquet under `OPENFDD_STORAGE_URL` is the restore path — no Feather, no migrate-from-old-format step.

### Auth model (human vs external AI)

| Who | Identity | Secret / token | Use |
|-----|----------|----------------|-----|
| Human operator | `admin` | `OPENFDD_ADMIN_PASSWORD` | Browser SPA login, mint edge kits, mint agent tokens |
| External AI (Cursor / Claude / Codex / OpenClaw) | `agent` | `OPENFDD_AGENT_PASSWORD` → operator JWT | MCP (`OPENFDD_MCP_TOKEN`) or JWT REST |
| Short-lived AI session | operator JWT | Admin `POST /api/auth/agent-token` | Prefer over long-lived agent password in MCP config |

**Rules for any AI:**

- Never put `OPENFDD_ADMIN_PASSWORD` into MCP / agent config.
- Never enable `OPENFDD_MCP_ALLOW_WRITES` unless a human explicitly asks; writes still need `confirm:true`.
- Keep MCP on private networking (Railway sidecar or VPN to central). Browser never gets MQTT or S3 secrets.
- Rotate agent password / re-mint JWT after demos.

### Mint agent JWT (from Railway shell or VPN that reaches private central)

```bash
TOKEN="$(curl -fsS -X POST http://openfdd-central.railway.internal:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"agent\",\"password\":\"$OPENFDD_AGENT_PASSWORD\"}" \
  | jq -r '.token // .access_token')"
# Local MCP host: OPENFDD_API_BASE=<reachable central URL> OPENFDD_MCP_TOKEN=$TOKEN
```

Or admin mints a TTL-bound token: `POST /api/auth/agent-token` with `Authorization: Bearer <admin JWT>` and body `{"ttl_secs":3600}`.

---

## Pre-deployment

- [ ] GHCR packages pull without login (or Railway has read-only GHCR credentials)
- [ ] Railway project created
- [ ] Decide `:nightly` vs `:sha-<7>`
- [ ] Default = **cloud MQTTS hub** (central + mqtt + web). Use CSV-only only if human opts out of mqtt

## Step 1 — Deploy `openfdd-central` first

- [ ] Image `ghcr.io/bbartling/openfdd-central:nightly` (or sha pin)
- [ ] Volume on `/workspace` (≥5GB)
- [ ] Vars (required):
  - `OPENFDD_JWT_SECRET` (≥32 chars)
  - `OPENFDD_ADMIN_PASSWORD` (human UI)
  - `OPENFDD_AGENT_PASSWORD` (external AI / MCP — **required** on Railway)
  - `OPENFDD_WORKSPACE=/workspace`
  - `OPENFDD_STORAGE_URL=file:///workspace/openfdd` (preferred) *or* legacy `OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet`
  - `OPENFDD_REACT_UI=1`
  - `OPENFDD_UI_GENERATION_DEFAULT=react`
- [ ] Optional low-RAM: `OPENFDD_QUERY_MEMORY_MB=512`, `OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill`
- [ ] For MQTTS hub: set Central MQTT client env to private broker (see [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md))
- [ ] Deploy and wait until `GET /api/health` returns 200
- [ ] From Railway shell: `getent hosts openfdd-central.railway.internal` and `curl -fsS http://openfdd-central.railway.internal:8080/api/health`

## Step 2 — Deploy `openfdd-mqtt` (default for OT / live sites)

Cloud MQTTS is the hub: on-prem fieldbus publishes into Railway MQTTS; Central ingests. Do **not** skip mqtt for live OT.

- [ ] Image `ghcr.io/bbartling/openfdd-mqtt:nightly`
- [ ] Private networking only (do not expose 8883 publicly without deliberate TLS/ACL design)
- [ ] Provision / mount broker certs + ACL as required by mqtt image / [deploy/mqtt](../../deploy/mqtt/README.md)
- [ ] Confirm broker listens on **8883** MQTTS inside the private network
- [ ] Confirm central can resolve and connect to mqtt on the private network

## Step 3 — Deploy `openfdd-web` after central is healthy

- [ ] Image `ghcr.io/bbartling/openfdd-web:nightly`
- [ ] `OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080` (no `http://`)
- [ ] Optional: `OPENFDD_NGINX_RESOLVER=auto` (default) or pin a nameserver from `/etc/resolv.conf`
- [ ] Public domain on **web only**
- [ ] Healthcheck path `/` (SPA); also verify `/api/health` via the web proxy after boot
- [ ] If older images fail with `host not found in upstream`: ensure central is healthy, then redeploy tip web (lazy DNS)

## Step 4 — Human UI + external AI auth verify

- [ ] `curl -fsS https://<public-web>/api/health`
- [ ] Browser login with **admin** (not agent)
- [ ] `GET /api/auth/status` → `auth_required: true`, `agent_login_configured: true`
- [ ] Mint **agent** JWT (login or `/api/auth/agent-token`) → local MCP `OPENFDD_MCP_TOKEN`
- [ ] Confirm Railway AI / deploy agent is **not** given admin password or MCP write access
- [ ] Never commit JWTs / agent password; rotate after demos
- [ ] Sidebar shows `3.3.N+shortsha`

## Step 5 — Product smoke

- [ ] CSV lab (if no mqtt): import `openfdd_package_v1`
- [ ] MQTTS hub: on-prem fieldbus connected; Operations MQTT monitor / ingest shows traffic
- [ ] Optional: Operations → MQTT → **Download edge kit**; mount ZIP at `/mqtt` on-prem (never ships CA private key)
- [ ] Optional private `openfdd-mcp` sidecar: `OPENFDD_API_BASE` → private central; read-first tools only until human enables writes

## Fieldbus stays on-prem

- [ ] Do **not** expect BACnet broadcast discovery on Railway
- [ ] Run `openfdd-fieldbus` on the OT LAN / VPN and point MQTTS at the cloud broker
- [ ] Do **not** ask Railway AI to run fieldbus or Open-FDD MCP for HVAC FDD

## Anti-patterns (fail the deploy if suggested)

- [ ] Public central or public MQTTS without explicit human approval
- [ ] Admin password in MCP / Cursor / Claude config
- [ ] Deploying fieldbus inside Railway for BACnet
- [ ] Reintroducing Feather dual-write / `OPENFDD_LEGACY_INGEST_MIRROR` (retired; Parquet under `OPENFDD_STORAGE_URL` only)
- [ ] Treating Railway AI as the FDD/HVAC assistant
- [ ] Recreating an empty `/workspace` volume on every image upgrade (destroys Parquet history)
