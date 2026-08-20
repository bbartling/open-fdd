---
title: Railway deployment
parent: Operations
nav_order: 4
---

# Railway deployment

> **Experimental cloud-lab path.** Open-FDD is local-first and currently intended for LAN/VPN/OT networks. The Railway recipe below is for CSV/package labs, demos, and controlled evaluation. It is **not** a claim that Open-FDD is production-hardened for direct public-internet exposure.

Open-FDD publishes a Rust/React container stack to GHCR. Railway can run the cloud-friendly subset without rebuilding the application.

## What to deploy

### Minimal cloud CSV lab

Deploy these two services:

| Railway service | Image | Container port | Exposure |
| --- | --- | ---: | --- |
| `openfdd-central` | `ghcr.io/bbartling/openfdd-central:nightly` | `8080` | Private preferred; web must reach it |
| `openfdd-web` | `ghcr.io/bbartling/openfdd-web:nightly` | `8080` | Public HTTP |

The browser talks to the React web service; the web image proxies `/api` to central in the normal Open-FDD topology. Central owns JWT auth, package import, historian storage, DataFusion FDD, and analytics.

Use `:nightly` for the latest green `master` channel or pin `:sha-<7>` for a reproducible deployment. Do not invent semver tags that are not published.

### Optional services

| Service | Image | Cloud notes |
| --- | --- | --- |
| MCP | `ghcr.io/bbartling/openfdd-mcp:nightly` | Optional agent sidecar. Set `OPENFDD_API_BASE` to central. |
| MQTT | `ghcr.io/bbartling/openfdd-mqtt:nightly` | Useful only when the deployment has a deliberate MQTT/OT topology and certificates. |
| Fieldbus | `ghcr.io/bbartling/openfdd-fieldbus:nightly` | BACnet/IP discovery normally needs access to the OT LAN/broadcast domain. A naive public Railway deployment cannot provide that. |

The real image set is `openfdd-central`, `openfdd-web`, `openfdd-fieldbus`, `openfdd-mqtt`, and `openfdd-mcp`. There is no `openfdd-commission` or `openfdd-mcp-rag` service in the product stack.

## Prerequisite: GHCR pull access

Railway must be able to pull the selected GHCR images.

For the easiest open-source deployment, make the five Open-FDD GHCR packages public in GitHub package settings. New GHCR packages can default to private, so re-check visibility whenever a new image/package is introduced.

If an unauthenticated pull is blocked, GHCR commonly responds with `401 Unauthorized`:

```bash
curl -sI https://ghcr.io/v2/bbartling/openfdd-central/manifests/nightly | head -1
curl -sI https://ghcr.io/v2/bbartling/openfdd-web/manifests/nightly | head -1
```

A public package should be pullable without a personal GitHub login. If package visibility must remain private, configure Railway with registry credentials instead of embedding credentials in repository files.

See [GHCR images](ghcr-images.md) for the image/tag contract.

## Create the Railway services

1. Create a Railway project.
2. Add a service from Docker image `ghcr.io/bbartling/openfdd-central:nightly`.
3. Add a service from Docker image `ghcr.io/bbartling/openfdd-web:nightly`.
4. Give the web service a public Railway domain.
5. Keep central private when possible and connect web-to-central over Railway private networking.
6. Configure persistent storage for central's workspace before relying on imported CSV/package history across redeploys.

Railway configuration should model the container ports, not the host-side ports shown by local Docker Compose. Both current central and web images listen on container port `8080`; local Compose maps web `3000:8080` only for developer convenience.

## Central variables

Set at least:

```text
OPENFDD_JWT_SECRET=<long deployment-unique random secret>
OPENFDD_ADMIN_PASSWORD=<strong deployment-unique password>
OPENFDD_WORKSPACE=/workspace
OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet
OPENFDD_REACT_UI=1
OPENFDD_UI_GENERATION_DEFAULT=react
```

`OPENFDD_JWT_SECRET` must be unique per deployment. Never commit either secret to Git.

For the minimal CSV lab, do not require the OT MQTT path merely because local `compose.react.yml` includes it. The target cloud recipe is central + web; OT services are optional and topology-dependent.

## Health and verification

Central's health endpoint is:

```text
GET /api/health
```

After deployment, verify central from a network location that can reach it:

```bash
curl -fsS https://<central-host>/api/health
```

Then open the web domain, log in with the configured admin password, import an `openfdd_package_v1` CSV package, and confirm Overview/Inspect/FDD routes can query the imported building.

Do **not** use bare `/health`; the product route is `/api/health`.

## MCP sidecar

If you add the optional MCP image, point it at central:

```text
OPENFDD_API_BASE=http://<central-private-host>:8080
OPENFDD_MCP_TOKEN=<JWT/token appropriate for the deployment>
```

Keep MCP private unless there is a deliberate authenticated agent gateway around it.

## OT / BACnet warning

Railway is not a substitute for an OT network.

BACnet/IP discovery commonly depends on local broadcast/subnet behavior, interface binding, router configuration, and access to building controls networks. `openfdd-fieldbus` therefore belongs on-site, behind a VPN/tunnel, or in infrastructure deliberately connected to the OT LAN. Do not advertise a one-click public-cloud deployment as automatic BACnet commissioning.

For a cloud CSV/package lab, omit fieldbus and MQTT entirely unless they are genuinely needed.

## Security posture

Open-FDD's current product contract is LAN/VPN/local-first. Internet-facing hardening is still an explicit future target in the project README. Treat Railway as an experimental lab/demo deployment unless your own network controls, authentication, secrets, TLS, persistence, backups, and exposure policy have been reviewed.

Never:

- commit `OPENFDD_JWT_SECRET`, admin passwords, registry tokens, or OT credentials;
- expose BACnet write paths to the public internet;
- assume a Railway public domain makes the whole stack production-safe;
- add Python/Streamlit commissioning services that are not part of the Rust/React product stack.

## Troubleshooting

### `401 Unauthorized` while pulling GHCR

The package is private or Railway lacks registry credentials. Make the package public or configure pull credentials.

### Health check fails

Check the container port (`8080` for central), use `/api/health`, and inspect central startup logs for missing JWT/auth configuration.

### Web loads but `/api` fails

Confirm web can reach central over Railway networking and that the web deployment preserves the normal `/api` proxy topology. Do not point browser JavaScript directly at an unrelated public central URL unless you intentionally redesign the proxy/security model.

### Imported data disappears after redeploy

Attach persistent storage for `/workspace`; central's imported packages, historian artifacts, and related state are not meant to live only on an ephemeral container filesystem.

### BACnet discovery finds nothing

That is expected on a generic cloud network. Run fieldbus where it has routed/broadcast access to the OT LAN or through an explicitly engineered VPN/router topology.

## One-click template target

The intended follow-up is a Railway Template for the **minimal cloud CSV lab** (`openfdd-web` + `openfdd-central`) with generated secrets, private service networking, persistent central storage, and `/api/health` verification. Once a real template is published and tested, the project README can expose Railway's official **Deploy on Railway** button.

Do not add a placeholder button that points to an unpublished or unverified template.
