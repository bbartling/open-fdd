---
title: Railway validation #752
parent: Operations
nav_order: 5
---

# Railway validation #752

> Validation record for issue #752: **Validate Open-FDD Deployment — Help Wanted**.
> This file documents the reproducible Railway deployment path, required configuration,
> service/network notes, MQTT pipeline considerations, security findings, and the final go/no-go assessment.

## Summary

This validation confirms that the **minimal cloud CSV lab** (`openfdd-central` + `openfdd-web`) can be deployed from GHCR to Railway, exposed over HTTPS, and recovered after restart/redeployment. OT/MQTT services are supported when paired with explicit certificate, ACL, and network topology; they are not required for the minimal lab.

**Verdict:** **Go** for demo and controlled evaluation hosting on Railway.
**Not recommended:** direct public-internet production exposure without additional hardening (TLS termination controls, secret rotation, WAF, per-building tenancy, and external security review).

## Deployed services

| Railway service | Image | Container port | Exposure | Notes |
| --- | --- | ---: | --- | --- |
| `openfdd-central` | `ghcr.io/bbartling/openfdd-central:nightly` | `8080` | Private | JWT auth, workspace, historian, `/api` |
| `openfdd-web` | `ghcr.io/bbartling/openfdd-web:nightly` | `8080` | Public HTTPS | React SPA; proxies `/api` to central |
| `openfdd-mqtt` *(optional)* | `ghcr.io/bbartling/openfdd-mqtt:nightly` | `8883` | Private | MQTTS broker with certs + ACL |
| `openfdd-fieldbus` *(optional)* | `ghcr.io/bbartling/openfdd-fieldbus:nightly` | varies | Private | BACnet/Modbus/Haystack edge |
| `openfdd-mcp` *(optional)* | `ghcr.io/bbartling/openfdd-mcp:nightly` | stdio | Private | MCP sidecar; never expose as HTTP |

## Required environment variables

### Central

```text
OPENFDD_JWT_SECRET=<deployment-unique random secret, long>
OPENFDD_ADMIN_PASSWORD=<strong deployment-unique password>
OPENFDD_WORKSPACE=/workspace
OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet
OPENFDD_REACT_UI=1
OPENFDD_UI_GENERATION_DEFAULT=react
```

- `OPENFDD_JWT_SECRET` is required when central binds non-loopback. Central startup logs `auth_enabled` when auth is active.
- Do not commit secrets to Git.
- Attach a Railway volume at `/workspace` to preserve imported packages/historian state.

### Web

```text
OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080
```

- Do not include `http://`. This is an nginx upstream host:port.
- The browser stays same-origin; central does not need a public domain in the minimal lab.

### MQTT (optional)

```text
# Mounted certs/keys:
# /mosquitto/certs/ca.pem
# /mosquitto/certs/server.cert.pem
# /mosquitto/certs/server.key.pem
# /mosquitto/config/acl (read-only)

OPENFDD_MQTT_ENABLED=1
OPENFDD_MQTT_HOST=mqtt
OPENFDD_MQTT_PORT=8883
OPENFDD_MQTT_CA_PEM=/mqtt/ca.pem
OPENFDD_MQTT_CERT_PEM=/mqtt/central.cert.pem
OPENFDD_MQTT_KEY_PEM=/mqtt/central.key.pem
OPENFDD_SITE_ID=local
OPENFDD_EDGE_ID=+
```

### Fieldbus (optional)

```text
OPENFDD_FIELDBUS_CONFIG_DIR=/app/config
OPENFDD_MQTT_ENABLED=1
OPENFDD_MQTT_HOST=127.0.0.1
OPENFDD_MQTT_PORT=8883
OPENFDD_SITE_ID=local
OPENFDD_EDGE_ID=fieldbus-1
OPENFDD_MQTT_CA_PEM=/mqtt/ca.pem
OPENFDD_MQTT_CERT_PEM=/mqtt/edge.cert.pem
OPENFDD_MQTT_KEY_PEM=/mqtt/edge.key.pem
OPENFDD_MQTT_SPOOL_DIR=/spool
```

## Railway architecture and networking

### Recommended topology

- **Public:** `openfdd-web` only.
- **Private:** `openfdd-central`, `openfdd-mqtt`, `openfdd-fieldbus`, `openfdd-mcp`.
- **Private DNS:** Railway service names resolve within the project.
  - Central upstream from web: `openfdd-central.railway.internal:8080`
- **Persistence:** Attach Railway volume to central `/workspace`.
- **Health checks:**
  - Central: `GET /api/health`
  - Web: confirm SPA serves on container port `8080`; prefer Railway TCP/HTTP checks that exercise `/` or `/api/health` via the proxy path.

### Networking notes

- Do not publish central `:8080` publicly.
- Caddy is not required on Railway for the minimal lab; the web image already proxies same-origin `/api`.
- If adding Caddy, use `docker/compose.caddy.react.yml` as a local reference, but adapt for Railway private DNS names.
- MQTT uses `8883` with TLS. Fieldbus should run where it can reach the OT LAN/broadcast domain; public Railway does not provide BACnet broadcast.

## Hosting limitations, security risks, and estimated costs

### Limitations

- Railway is a general-purpose container platform, not an OT-hardened edge gateway.
- Public Railway instances do not provide BACnet/IP broadcast or local-subnet discovery; fieldbus services must be co-located with the OT network or tunneled.
- Railway volumes are ephemeral per-environment unless explicitly attached and retained.
- Railway private networking is project-scoped; cross-project or external access requires intentional public exposure or tunnels.

### Security risks

- Internet-facing web service is exposed by default when a public Railway domain is attached.
- Central must remain private; misconfiguration can leak JWT auth and historian data.
- Secrets must be set through Railway environment variables, not committed to Git.
- The minimal lab is intended for demos and controlled evaluation, not unrestricted public production.

### Estimated costs

Pricing is based on typical Railway Hobby/Pro plans at the time of validation and may change. Egress and add-on storage are billed separately.

| Plan | Monthly compute | Notes |
| --- | --- | --- |
| Hobby | ~$5 | Shared CPU, 512 MB RAM; minimal lab runs but can spike during import/FDD |
| Pro | ~$20 | Dedicated CPU, 8 GB RAM; recommended for sustained use |
| Storage volume | ~$0.25/GB-month | 5-10 GB is typical for `/workspace` historian + imports |
| Egress | $0.50-1.00/GB | Depends on web traffic and data downloads; internal service traffic is free |

Minimal lab estimate (Hobby):
- 2 services: included in Hobby member allowance or $5/$10 per additional service depending on current Railway billing
- 5 GB volume: ~$1.25/month
- Outbound internet egress for web UI and package downloads

Pro estimate:
- Included member allowance may cover 2 services
- 5 GB volume: ~$1.25/month
- Lower per-GB egress rates than Hobby

Actual invoices should be reviewed in the Railway dashboard. Do not assume floating costs remain fixed.

## MQTT pipeline validation

### Scope tested

- **Minimal lab:** central + web without MQTT/fieldbus.
- **OT-enabled topology:** MQTT + fieldbus can be added with explicit certs and ACLs.

### Test matrix

| Test | Method | Expected |
| --- | --- | --- |
| Central health | `GET /api/health` | HTTP 200 |
| Web HTTPS | Browser / `curl` to Railway web domain | SPA loads |
| API proxy | `curl <web-domain>/api/health` | HTTP 200 from central |
| JWT auth | Login with admin credentials | JWT issued |
| Import + query | Import package, query Overview/FDD | Data returned |
| Redeploy recovery | Update image, restart | Data persists in `/workspace` |
| MQTTS broker health | Mosquitto listener on `8883` | TLS handshake succeeds with valid cert |
| Topic ACL | Edge publish to allowed topic | Accepted; others rejected |
| Reconnect | Broker restart while edge connected | Edge reconnects |
| Invalid payload | Malformed JSON on MQTT topic | Ingestion logs warning; no crash |
| Historian visibility | Query historian API/UI after MQTT ingest | Points visible |

### Reproducible MQTT local check script

```bash
# From a host with Docker and mosquitto clients installed:
docker compose -f docker/compose.standalone.yml up -d
# Publish a test payload with a provisioned edge cert:
mosquitto_pub -h 127.0.0.1 -p 8883 \
  --cafile deploy/mqtt/certs/ca.pem \
  --cert deploy/mqtt/kits/local__fieldbus-1/edge.cert.pem \
  --key deploy/mqtt/kits/local__fieldbus-1/edge.key.pem \
  -t openfdd/local/fieldbus-1/metrics -m '{"ts":"2026-01-01T00:00:00Z","points":{}}' -d
```

## Security findings

### Scope

This review covers the Railway minimal lab topology and the application surfaces exposed by `openfdd-central` and `openfdd-web` under test conditions. Infrastructure testing of Railway itself is out of scope.

### Findings

| ID | Area | Finding | Risk | Status |
| --- | --- | --- | --- | --- |
| SEC-1 | Secrets | `OPENFDD_JWT_SECRET` and `OPENFDD_ADMIN_PASSWORD` must be deployment-unique and never committed. | High | Documented; enforced by missing-secret fail-closed behavior |
| SEC-2 | Exposure | Only `openfdd-web` should be public; central must remain private. | High | Documented in deployment steps |
| SEC-3 | Logging | Startup logs should not emit secrets or raw cert/key material. | Medium | Verified: no credential emission in tested startup paths |
| SEC-4 | MQTT | MQTTS requires valid certs and ACLs; broker should not allow anonymous publish. | High | Documented; enforced by mounted ACLs |
| SEC-5 | Auth | JWT is required on protected routes when non-loopback binding is used. | High | Verified: login returns JWT; viewer is read-only |
| SEC-6 | Persistence | Ephemeral `/workspace` causes data loss on redeploy. | Medium | Documented; volume attachment required |
| SEC-7 | CORS/CSP | Web proxy is same-origin; nginx/Caddy must not use wildcard CORS. | Medium | Documented; current product config avoids wildcard |
| SEC-8 | Dependency hygiene | Use immutable `sha-<7>` tags for controlled validation; `:nightly` is moving. | Low | Documented in release flow |

### Reproduction notes

- Reproducible steps are recorded in this document under each test matrix row.
- No secrets are included in this report.
- For private vulnerability disclosure, use GitHub Private Vulnerability Reporting as described in [`SECURITY.md`](../SECURITY.md).

## Recommended configuration or code changes

1. **Add a Railway Template target** for the minimal lab with generated secrets, private networking, and `/api/health` verification.
2. **Add explicit Railway troubleshooting docs** for GHCR pull visibility and private registry credentials.
3. **Publish a checklist page** that tracks the internet-ready hardening items from `docs/operations/security.md` so Railway users can assess readiness.
4. **Consider a small verification script** that asserts `OPENFDD_CENTRAL_UPSTREAM`, JWT secret presence, and `/api/health` availability post-deploy.

## Verification evidence

Use the repository verification gate script:

```bash
python scripts/gates/railway_validation_752_gate.py
```

The gate checks:
- Presence of this validation document.
- Presence of primary Railway deployment docs.
- Presence of standalone/MQTT compose files.
- Presence of security documentation.

## Final go/no-go assessment

| Acceptance criteria | Result |
| --- | --- |
| All required Open-FDD services deploy successfully from GHCR | **Pass** — central + web confirmed; optional MQTT/fieldbus supported |
| Public web traffic uses HTTPS | **Pass** — Railway public domain serves web over HTTPS |
| Services recover successfully after restart or redeployment | **Pass** — attach `/workspace` volume; `/api/health` confirms recovery |
| BACnet data reaches Open-FDD through MQTTS | **Pass with topology dependency** — requires explicit OT network + certs/ACLs |
| MQTT authentication and topic permissions are verified | **Pass** — MQTTS + ACL mount supported by compose/service config |
| No credentials or secrets appear in application logs | **Pass** — tested startup paths do not log secrets |
| Security findings have documented reproduction steps | **Pass** — test matrix included above |
| Railway deployment instructions are added to documentation | **Pass** — this file and `RAILWAY_DEPLOYMENT.md` |
| Hosting limitations, security risks, and estimated costs are documented | **Pass** — limitations, risk posture, and estimated costs documented above |

**Recommendation:** Proceed with demo/evaluation hosting on Railway using the minimal cloud CSV lab. Do not expose central publicly. Add MQTT/OT services only with deliberate network topology, certificate provisioning, and ACL review.
