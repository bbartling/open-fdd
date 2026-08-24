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

This validation covers the **minimal cloud CSV lab** (`openfdd-central` + local `openfdd-web` Overview bundle) on Railway. It does **not** claim that MQTT/fieldbus behavior, restart recovery, or secret-free logs have been validated on Railway unless dated evidence is attached.

**Verdict:** **Go** for demo and controlled evaluation of the minimal central + web path.
**Not recommended:** direct public-internet production exposure without additional hardening.

## Deployed services

Repository policy requires immutable image selection for backend services and a local web bundle for unmerged frontend code.

| Railway service | Image / artifact | Container port | Exposure | Validation status |
| --- | --- | ---: | --- | --- |
| `openfdd-central` | `ghcr.io/bbartling/openfdd-central:sha-<newest-by-created>` | `8080` | Private | Required; exact tag must be recorded before recreation |
| `openfdd-web` | **Local Overview bundle, not GHCR** | `8080` | Public HTTPS | Minimal-path web artifact |
| `openfdd-mqtt` *(optional)* | `ghcr.io/bbartling/openfdd-mqtt:sha-<newest-by-created>` | `8883` | Private | Conditional / not Railway-validated here |
| `openfdd-fieldbus` *(optional)* | `ghcr.io/bbartling/openfdd-fieldbus:sha-<newest-by-created>` | varies | Private | Conditional / not Railway-validated here |

Before recreating backend services, resolve and record the newest-by-OCI-created immutable tags with:

```bash
python scripts/ghcr_newest_by_created.py --json openfdd-central openfdd-mqtt openfdd-fieldbus
export OPENFDD_IMAGE_TAG=sha-<resolved-central-tag>
```

Do not substitute moving image tags for a reproducible validation record.

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

- `OPENFDD_JWT_SECRET` is required for every compose deployment.
- Non-loopback exposure is a separate security consideration: central must remain authenticated and private.
- Do not commit secrets to Git.
- Attach a Railway volume at `/workspace` to preserve imported packages/historian state.

### Web

```text
OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080
```

- Do not include `http://`; this is an nginx upstream host:port.
- The browser stays same-origin.
- For this unmerged validation path, serve the local Overview bundle rather than GHCR `openfdd-web`.

### MQTT / fieldbus

MQTT and fieldbus are optional and **not claimed as Railway-validated** in this record. If enabled, use private networking, TLS certificates, ACLs, and immutable `sha-*` backend images selected newest-by-created.

## Railway architecture and networking

- **Public:** local web bundle only.
- **Private:** central, MQTT, fieldbus.
- **Private DNS:** Railway service names inside the project.
- **Persistence:** attach a volume at `/workspace`.
- **Health check:** central `GET /api/health`.

## Security findings

- Central must remain private.
- `OPENFDD_JWT_SECRET` and `OPENFDD_ADMIN_PASSWORD` are always required deployment secrets.
- Do not log secrets or raw payload material.
- Do not use moving image tags for reproducible validation.
- For private vulnerability disclosure, use GitHub Private Vulnerability Reporting as described in [`SECURITY.md`](../../SECURITY.md).

## Verification evidence

Use the repository gate:

```bash
python scripts/gates/railway_validation_752_gate.py
```

The gate validates document claims and required values; it does **not** manufacture missing Railway evidence.

## Final go/no-go assessment

| Acceptance criteria | Result |
| --- | --- |
| `openfdd-central` uses immutable newest-by-created GHCR `sha-*` image | **Conditional** — exact resolved tag must be recorded before recreation |
| `openfdd-web` uses local Overview bundle rather than GHCR | **Pass** |
| Public web traffic uses HTTPS | **Pass** for the documented minimal path |
| Services recover successfully after restart or redeployment | **Not verified** — requires dated Railway logs / command output |
| BACnet data reaches Open-FDD through MQTTS | **Not verified** — requires dated Railway MQTT/fieldbus evidence |
| MQTT authentication and topic permissions are verified | **Not verified** — requires dated Railway broker/ACL evidence |
| No credentials or secrets appear in application logs | **Conditional** — code/config intent documented; Railway log evidence not attached |
| Security findings have documented reproduction guidance | **Pass** |
| Railway deployment instructions are documented | **Pass** |
| Hosting limitations and security risks are documented | **Pass** |

**Recommendation:** Proceed only with the minimal central + local-web demo/evaluation path. Do not claim restart, MQTT/fieldbus, ACL, or log-validation success until dated evidence is attached.
