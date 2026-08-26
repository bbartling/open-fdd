---
title: Railway deployment
parent: Operations
nav_order: 4
---

# Railway deployment

> **Experimental cloud path.** Open-FDD is local-first and currently intended for LAN/VPN/OT networks. The Railway recipes below are for labs, demos, and controlled evaluation. They are **not** a claim that Open-FDD is production-hardened for direct public-internet exposure.

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
OPENFDD_JWT_SECRET=<long deployment-unique random secret>
OPENFDD_ADMIN_PASSWORD=<strong deployment-unique password>
OPENFDD_WORKSPACE=/workspace
OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet
OPENFDD_REACT_UI=1
OPENFDD_UI_GENERATION_DEFAULT=react
```

For MQTTS hub, also configure Central’s MQTT client settings to the private broker (host/port/certs) per stack env conventions used in Compose — never commit secrets.

## Web variables

```text
OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080
OPENFDD_NGINX_RESOLVER=auto
```

Do not include `http://` in `OPENFDD_CENTRAL_UPSTREAM`. `OPENFDD_NGINX_RESOLVER=auto` (image default) picks the first nameserver from `/etc/resolv.conf`; override with an explicit IP if needed.

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
OPENFDD_MCP_TOKEN=<JWT/token appropriate for the deployment>
```

Keep MCP private unless there is a deliberate authenticated agent gateway.

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
