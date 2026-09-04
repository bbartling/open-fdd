---
title: Railway deployment
parent: Operations
nav_order: 4
---

# Railway deployment

> **Experimental cloud path.** Open-FDD is local-first and currently intended for LAN/VPN/OT networks. The Railway recipes below are for labs, demos, and controlled evaluation. They are **not** a claim that Open-FDD is production-hardened for direct public-internet exposure.

**Related agent handbooks**

| Doc | Role |
| --- | --- |
| [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md) | Firewall / on-prem Compose hub — **plain HTTP**, no product TLS yet |
| [STRESS_CLOSEOUT.md](STRESS_CLOSEOUT.md) | Rigorous stress LAST (Railway hub + CSV + ZAP) |
| [PATCH_CYCLE.md](PATCH_CYCLE.md) | Tiny VERSION rev template → Cursor plan YAML |
| [backup-update-restore.md](backup-update-restore.md) | Backup before every central re-pin |
| Skill [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md) | CLI auth / re-pin on bensbench |

Open-FDD publishes a Rust/React container stack to GHCR. Railway can run the cloud-friendly subset directly from those prebuilt images without rebuilding the application.

**Operator checklist:** [RAILWAY_DEPLOYMENT_CHECKLIST.md](RAILWAY_DEPLOYMENT_CHECKLIST.md).

## Deployment sequencing (required)

Railway does **not** guarantee peer service DNS or health before dependents start. Agents and humans must:

1. Deploy **`openfdd-central`** and wait until `GET /api/health` returns **200**.
2. Deploy **`openfdd-mqtt`** when this is a **cloud MQTTS hub** (default for live OT).
3. Deploy **`openfdd-web`** last, with `OPENFDD_CENTRAL_UPSTREAM` pointing at central’s private DNS.

Healthcheck windows on Railway are often ~30s. If web starts while central’s `.railway.internal` name is not yet resolvable, **old** web images failed nginx startup with `host not found in upstream`. Tip `openfdd-web` images use **lazy DNS** (nginx `resolver` + variable `proxy_pass`) so the process can boot and resolve central on the first `/api` request. Still deploy central first — lazy DNS does not invent a healthy peer.

## What to deploy

### A. Cloud MQTTS hub (preferred for live OT)

| Railway service | Image | Container port | Exposure |
| --- | --- | ---: | --- |
| `openfdd-central` | `ghcr.io/bbartling/openfdd-central:nightly` | `8080` | Private |
| `openfdd-mqtt` | `ghcr.io/bbartling/openfdd-mqtt:nightly` | `8883` | Private MQTTS |
| `openfdd-web` | `ghcr.io/bbartling/openfdd-web:nightly` | `8080` | Public HTTP |

**Why mqtt is on by default for this path:** the cloud service’s job is to host **MQTTS** so on-prem `openfdd-fieldbus` can publish securely into Central. CSV-only labs may omit mqtt; live OT should not.

Keep **fieldbus on-prem** (OT LAN / VPN). Do not expect BACnet discovery inside Railway.

### B. Minimal CSV / package lab

| Railway service | Image | Container port | Exposure |
| --- | --- | ---: | --- |
| `openfdd-central` | `ghcr.io/bbartling/openfdd-central:nightly` | `8080` | Private preferred |
| `openfdd-web` | `ghcr.io/bbartling/openfdd-web:nightly` | `8080` | Public HTTP |

The browser talks to the React web service; the web image proxies same-origin `/api` and `/twins` to central.

Use `:nightly` for the latest green `master` channel or pin `:sha-<7>` for a reproducible deployment. Do not invent semver tags that are not published.

### Optional

| Service | Image | Cloud notes |
| --- | --- | --- |
| MCP | `ghcr.io/bbartling/openfdd-mcp:nightly` | Optional agent sidecar. Set `OPENFDD_API_BASE` to central. |
| Fieldbus | `ghcr.io/bbartling/openfdd-fieldbus:nightly` | Run on-prem / OT-connected hosts; publish MQTTS to cloud mqtt. |

The real image set is `openfdd-central`, `openfdd-web`, `openfdd-fieldbus`, `openfdd-mqtt`, and `openfdd-mcp`. There is no `openfdd-commission` or `openfdd-mcp-rag` service in the product stack.

## Prerequisite: GHCR pull access

Railway must be able to pull the selected GHCR images.

For the easiest open-source deployment, make the Open-FDD GHCR packages public in GitHub package settings. New GHCR packages can default to private, so re-check visibility whenever a new image/package is introduced.

```bash
docker logout ghcr.io 2>/dev/null || true
docker pull ghcr.io/bbartling/openfdd-central:nightly
docker pull ghcr.io/bbartling/openfdd-web:nightly
docker pull ghcr.io/bbartling/openfdd-mqtt:nightly
```

If package visibility must remain private, Railway supports GHCR registry credentials (plan-dependent). Use a GitHub token scoped to `read:packages` only. Never embed registry credentials in repository files.

See [GHCR images](ghcr-images.md) for the image/tag contract.

## Railway CLI (bensbench / agent hosts)

Verified on bensbench (**2026-08-29**): **`@railway/cli` 5.45.7** (`npm i -g @railway/cli`).  
**Auth:** `railway login` (browser) works. Optional agent token: `~/.config/railway/bensbench.env` (`RAILWAY_TOKEN`).  
**Link:** `~/open-fdd` → project **`gleaming-cooperation`** / env **`production`**.  
Agent skill: [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md). Checklist: [RAILWAY_DEPLOYMENT_CHECKLIST.md](RAILWAY_DEPLOYMENT_CHECKLIST.md) § *CLI*.

This is **deploy ops**, not Open-FDD MCP. FDD agents use [`mcp/`](../../mcp/) + JWT to private central — see [mcp/INSTRUCTIONS.md](../../mcp/INSTRUCTIONS.md).

### Live service names (gleaming-cooperation)

| Role | Railway service name | Private DNS / notes |
| --- | --- | --- |
| central | `openfdd-central-cQ-F` | `openfdd-central-cQ-F.railway.internal:8080` |
| mqtt | `openfdd-mqtt` | Private MQTTS |
| web | `openfdd-web` | Public; `OPENFDD_CENTRAL_UPSTREAM=openfdd-central-cQ-F.railway.internal:8080` |

Always confirm with `railway status` before scripting — the central name is **not** always `openfdd-central`.

### Install

```bash
npm i -g @railway/cli
railway --version   # expect 5.x
```

Optional (Railway’s own Cursor skills + MCP — **not** a substitute for Open-FDD agent law or `openfdd-mcp`):

```bash
railway setup agent -y
```

### Auth

**Verified path (human):**

```bash
railway login
railway whoami
cd ~/open-fdd && railway link   # gleaming-cooperation / production
railway status
```

**Agent / non-interactive:** create a Railway token → `~/.config/railway/bensbench.env` with `RAILWAY_TOKEN=…` (never commit). Example stub: `~/.config/railway/bensbench.env.example`.

```bash
set -a && source ~/.config/railway/bensbench.env && set +a
railway whoami
```

### Re-pin tip images after a GHCR soak (operator)

After a patch-cycle tip is published (e.g. `sha-9667888`), re-pin **central → mqtt → web**. Prefer immutable `:sha-<7>`.

```bash
cd ~/open-fdd
SHA=sha-9667888
CENTRAL_SVC=openfdd-central-cQ-F   # from railway status

railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${SHA}"
# wait until private central /api/health is 200

railway service source connect --service openfdd-mqtt \
  --image "ghcr.io/bbartling/openfdd-mqtt:${SHA}"

railway variable set OPENFDD_NGINX_RESOLVER=auto --service openfdd-web
railway service source connect --service openfdd-web \
  --image "ghcr.io/bbartling/openfdd-web:${SHA}"
```

If only env changed and the image source is already correct, `railway redeploy -s <service> -y` is enough. Confirm public SPA + `/api/health` after web comes up.

**Known failure without tip web:** older images crash with `invalid port in resolver "fd12::10"` — fixed in tip `openfdd-web` entrypoint; re-pin + `OPENFDD_NGINX_RESOLVER=auto`.

**Known failure (fixed in 3.3.9+):** variable `proxy_pass http://$openfdd_central/api/;` doubles the path to `/api/api/…` → empty **404**. Tip web uses `proxy_pass http://$openfdd_central;` (no URI suffix).

### Continuous patch train (bosspi → Railway)

Cloud soak gate is **not** bench dual-MQTT. Keep tiny platform revs until:

1. Public web `/api/health` **200** (L1)
2. `openfdd-mqtt` **Online** with certs volume + central ingest (L3)
3. **bosspi** tip fieldbus publishes MQTTS into Railway; `has_telemetry` + ingest moving (L4 + stream health)
4. Hub containers stay Online without recurring crash/log errors
5. Then FDD smoke on that site (L5)

Each bump: squash-merge → delete branch → **0 open PRs** → tip Actions green → GHCR Publish → re-pin Railway + Pi → update [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md) (CLOSE validated rows; keep unfinished deferred). Ops-only (volume/certs/TCP proxy) still counts as a loop iteration.

**Primary topology:** `bosspi openfdd-fieldbus` → Railway mqtt `:8883` (TCP proxy / VPN) → central → public web. Bensbench = Railway CLI / cert staging only.

Do not deploy fieldbus on Railway.

## Create the Railway services

1. Create a Railway project.
2. Add **`openfdd-central`** from GHCR; attach volume at `/workspace`; set secrets; deploy; wait for `/api/health`.
3. For MQTTS hub: add **`openfdd-mqtt`** (private); provision certs/ACL per mqtt image docs; confirm **8883**.
4. Add **`openfdd-web`** from GHCR; set upstream; give **only web** a public domain; deploy.
5. Keep central (and mqtt) private; use Railway private networking.

Both central and web listen on container port `8080`. Local Compose maps web `3000:8080` for developer convenience only.

Railway private DNS: `openfdd-central.railway.internal:8080`.

## Central variables

```text
OPENFDD_JWT_SECRET=<long deployment-unique random secret, ≥32 chars>
OPENFDD_ADMIN_PASSWORD=<strong deployment-unique password — human browser UI only>
OPENFDD_AGENT_PASSWORD=<strong password for external FDD AI / MCP — not the admin password>
OPENFDD_WORKSPACE=/workspace
OPENFDD_STORAGE_URL=file:///workspace/openfdd
# Legacy alias (prefer STORAGE_URL on new deploys): OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet
OPENFDD_REACT_UI=1
OPENFDD_UI_GENERATION_DEFAULT=react
```

Store these only in Railway **Variables / Secrets**. Never commit them, never paste JWTs into chat transcripts or repo files.

**Default hub = central + mqtt + web.** Railway AI / deploy assistants should follow [RAILWAY_DEPLOYMENT_CHECKLIST.md](RAILWAY_DEPLOYMENT_CHECKLIST.md) § *AI / Railway-assistant bootstrap context*. Railway AI does **not** run Open-FDD MCP or HVAC FDD — that is a **local external agent** with an operator JWT after deploy.

| Identity | Login | JWT role | Use |
| --- | --- | --- | --- |
| `admin` | `OPENFDD_ADMIN_PASSWORD` | admin | Browser UI, mint agent tokens, edge kits |
| `agent` | `OPENFDD_AGENT_PASSWORD` | operator | Cursor / MCP / REST FDD assistance (local AI → cloud central) |

Prefer **`agent`** for remote AI assistance. Do not share the admin password with MCP hosts. Do not treat Railway’s built-in assistant as the FDD/HVAC agent.

### Secure agent auth on Railway (Cursor / MCP)

1. Set `OPENFDD_JWT_SECRET`, `OPENFDD_ADMIN_PASSWORD`, and `OPENFDD_AGENT_PASSWORD` on **central**.
2. Keep central (and MCP) on Railway **private networking** — only `openfdd-web` gets a public domain.
3. Mint a short-lived operator JWT (do not log the token):

```bash
# From a trusted shell that can reach central (Railway shell / VPN), either:
# A) agent password login
TOKEN="$(curl -fsS -X POST http://openfdd-central.railway.internal:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"agent\",\"password\":\"$OPENFDD_AGENT_PASSWORD\"}" \
  | jq -r '.token // .access_token')"

# B) admin mints a short-lived agent token (ttl_secs default 3600, max 86400)
ADMIN_TOKEN="$(curl -fsS -X POST http://openfdd-central.railway.internal:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$OPENFDD_ADMIN_PASSWORD\"}" \
  | jq -r '.token // .access_token')"
TOKEN="$(curl -fsS -X POST http://openfdd-central.railway.internal:8080/api/auth/agent-token \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"ttl_secs":3600}' \
  | jq -r '.token // .access_token')"
```

4. Point MCP at private central with that JWT only:

```text
OPENFDD_API_BASE=http://openfdd-central.railway.internal:8080
OPENFDD_MCP_TOKEN=<operator JWT from step 3>
# Writes stay off unless deliberate:
# OPENFDD_MCP_ALLOW_WRITES=1
```

5. Rotate: change `OPENFDD_AGENT_PASSWORD` / re-mint JWT; treat stolen JWTs as compromised until expiry.

`GET /api/auth/status` reports `agent_login_configured` when the agent password is set.

For MQTTS hub, also configure Central’s MQTT client settings to the private broker (host/port/certs) per stack env conventions used in Compose — never commit secrets.

## Web variables

```text
OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080
OPENFDD_NGINX_RESOLVER=auto
```

Do not include `http://` in `OPENFDD_CENTRAL_UPSTREAM`. `OPENFDD_NGINX_RESOLVER=auto` (image default) prefers an IPv4 nameserver from `/etc/resolv.conf`, then brackets IPv6 (`[fd12::10]`) so nginx does not treat `::` as a port. Override with an explicit IP if needed.

## Health and verification

```bash
curl -fsS http://openfdd-central.railway.internal:8080/api/health
curl -fsS https://<web-domain>/api/health
getent hosts openfdd-central.railway.internal
```

Then open the web domain, log in, and for CSV labs import an `openfdd_package_v1` zip. For MQTTS hubs, confirm Operations MQTT monitor / ingest after fieldbus publishes.

Do **not** use bare `/health`; the product route is `/api/health`.

## MCP sidecar

```text
OPENFDD_API_BASE=http://openfdd-central.railway.internal:8080
OPENFDD_MCP_TOKEN=<operator JWT from agent login or POST /api/auth/agent-token>
```

Keep MCP **private**. Prefer `OPENFDD_AGENT_PASSWORD` / mint endpoint over putting `OPENFDD_ADMIN_PASSWORD` into any MCP host. Leave `OPENFDD_MCP_ALLOW_WRITES` unset unless an operator explicitly enables mutating tools (`confirm:true` still required).

## OT / BACnet warning

Railway is not a substitute for an OT network. BACnet/IP discovery belongs with on-prem fieldbus. Cloud MQTTS is the transport hub, not a BAS broadcast domain.

## GHCR release flow for Railway

A merge to `master` triggers the stack GHCR publisher (`openfdd-central`, `openfdd-web`, `openfdd-fieldbus`, `openfdd-mqtt`) and the separate MCP publisher.

Before redeploying Railway:

1. wait for publish workflows to finish green;
2. resolve the immutable `sha-<7>` tag;
3. verify `:nightly` digest if using the floating channel;
4. redeploy services (image push alone may not restart Railway).

## Security posture

Treat Railway as an experimental lab/demo unless your own controls, TLS, persistence, backups, and exposure policy have been reviewed.

Never:

- commit secrets or OT credentials;
- share `OPENFDD_ADMIN_PASSWORD` with MCP hosts (use `OPENFDD_AGENT_PASSWORD` or `/api/auth/agent-token`);
- embed long-lived JWTs in Cursor config checked into git;
- expose BACnet write paths publicly;
- publish MQTTS `8883` to the open internet without a deliberate ACL/TLS design;
- assume a public web domain makes the whole stack production-safe.

Report vulnerabilities via [GitHub Private Vulnerability Reporting](../../SECURITY.md).

## Troubleshooting

### `nginx: [emerg] host not found in upstream "….railway.internal"`

**Cause:** nginx resolved the upstream hostname at **startup** before Railway private DNS had the peer.

**Fix (tip images):** lazy DNS — variable upstream + `resolver` / `OPENFDD_NGINX_RESOLVER=auto`. Redeploy web on a nightly built after that change.

**Operational:**

1. Ensure central is deployed and `GET /api/health` is 200.
2. Confirm `OPENFDD_CENTRAL_UPSTREAM` matches the Railway **service name** exactly.
3. From Railway shell: `getent hosts openfdd-central.railway.internal`.
4. Increase healthcheck retry window if central is slow; still prefer deploy-central-first.
5. Retry web deploy after central is healthy.

### GHCR image will not pull

Confirm package visibility or configure read-only GHCR credentials.

### Health check fails (web)

Confirm container port `8080`. If `/` never becomes ready, inspect nginx logs for upstream/DNS errors. Prefer verifying `/api/health` through the web proxy once nginx is up.

### Web loads but `/api` fails

Confirm `OPENFDD_CENTRAL_UPSTREAM`, same Railway project/environment, and central on `8080`.

### Imported data disappears after redeploy

Attach persistent storage for `/workspace`.

### BACnet discovery finds nothing

Expected on generic cloud networks — run fieldbus on the OT LAN and use cloud MQTTS.

## One-click template target

Draft notes live under [`railway/`](../../railway/README.md). A verified Railway Template should create **central → mqtt → web**, generate secrets, attach `/workspace`, set `OPENFDD_CENTRAL_UPSTREAM`, keep central/mqtt private, and document first login. Do not add a README “Deploy on Railway” button until that template is published and tested.

Railway currently lacks a first-class `dependsOn` / deploy-after field for private DNS peers — document sequencing in checklists until the platform supports it.

## CLI (operator / agent)

See § [Railway CLI](#railway-cli-bensbench--agent-hosts) above and skill [`openfdd-railway-cli`](../../openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md). Bensbench: CLI **5.45.7**, `railway login` verified, project **`gleaming-cooperation`** / **`production`**.
