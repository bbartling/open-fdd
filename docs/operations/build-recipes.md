---
title: Build recipes
parent: Operations
nav_order: 2
---

# Compose build recipes

Open-FDD ships as a small container stack. Every deployment is one of four
compose recipes under `docker/`, brought up with `scripts/openfdd_stack_up.sh`.
The stack images are:

| Image | Role |
|-------|------|
| `ghcr.io/bbartling/openfdd-central` | API + FDD engine (DataFusion rule registry) |
| `ghcr.io/bbartling/openfdd-ui` | Caddy static UI, proxies `/api` to central |
| `ghcr.io/bbartling/openfdd-fieldbus` | BACnet/IP poller, publishes over MQTTS |
| `ghcr.io/bbartling/openfdd-mqtt` | Mosquitto broker (MQTTS on 8883) |
| `ghcr.io/bbartling/openfdd-mcp` | Slim Rust MCP server (talks to central) |

All images use the same channel tags (`nightly`, `beta`, `latest`, pinned
semver, `sha-*`) — see [Release channels](release-channels.html) and
[GHCR images](ghcr-images.html).

## Recipes at a glance

| Recipe | Compose file | Services | Pulls |
|--------|--------------|----------|-------|
| `standalone` | `docker/compose.standalone.yml` | mqtt + central + ui + fieldbus | central, ui, fieldbus, mqtt |
| `central` | `docker/compose.central.yml` | mqtt + central + ui | central, ui, mqtt |
| `edge` | `docker/compose.edge.yml` | fieldbus only | fieldbus |
| `csv` | `docker/compose.csv.yml` | central + ui (`OPENFDD_MQTT_ENABLED=0`) | central, ui |

## Bring a recipe up

`openfdd_stack_up.sh` pulls the GHCR images for the recipe (unless
`--no-pull`/`--build`), runs `docker compose up -d`, and waits on
`GET /api/health` (except the `edge` recipe):

```bash
./scripts/openfdd_stack_up.sh standalone     # pull nightly + up
./scripts/openfdd_stack_up.sh central
./scripts/openfdd_stack_up.sh csv
OPENFDD_MQTT_HOST=hub.example.com \
OPENFDD_SITE_ID=site-a \
OPENFDD_EDGE_KIT_DIR=./deploy/mqtt/kits/site-a__fieldbus-1 \
  ./scripts/openfdd_stack_up.sh edge

# Build locally from source instead of pulling GHCR:
./scripts/openfdd_stack_up.sh standalone --build
```

Pull without starting:

```bash
./scripts/openfdd_stack_pull.sh standalone   # or central|edge|csv|mcp|all
```

After boot: UI on `http://<host>:3000`, API on `http://<host>:8080/api/health`.

## Recipes in detail

### standalone — everything on one host

`mqtt + central + ui + fieldbus`. The all-on-edge box: BACnet polling,
broker, engine, and UI on a single machine. `fieldbus` runs on the host
network for BACnet/IP.

```bash
./scripts/openfdd_stack_up.sh standalone
```

### central — hub for remote edges

`mqtt + central + ui`. Run the hub in the cloud or on a local server; remote
fieldbus edges attach over MQTTS with the `edge` recipe.

```bash
./scripts/openfdd_stack_up.sh central
```

### edge — fieldbus attach

`fieldbus` only, host networking for BACnet/IP, needs outbound TCP 8883 to a
central broker. Required env: `OPENFDD_MQTT_HOST`, `OPENFDD_SITE_ID`,
`OPENFDD_EDGE_KIT_DIR` (path to the provisioning kit for this edge).

```bash
OPENFDD_MQTT_HOST=hub.example.com \
OPENFDD_SITE_ID=site-a \
OPENFDD_EDGE_KIT_DIR=./deploy/mqtt/kits/site-a__fieldbus-1 \
  ./scripts/openfdd_stack_up.sh edge
```

### csv — CSV-only, no live OT

`central + ui` with `OPENFDD_MQTT_ENABLED=0` — no broker or fieldbus images
pulled. Start FDD jobs from bulk CSV upload in the UI when there are no live
BACnet drivers.

```bash
./scripts/openfdd_stack_up.sh csv
```

## Environment reference

| Variable | Default | Notes |
|----------|---------|-------|
| `OPENFDD_IMAGE_TAG` | `nightly` | Channel/tag for every stack image |
| `OPENFDD_*_IMAGE` | `ghcr.io/bbartling/openfdd-*:<tag>` | Override a single image (e.g. `OPENFDD_CENTRAL_IMAGE`) |
| `OPENFDD_SITE_ID` | `local` | Site identifier / MQTT topic namespace |
| `OPENFDD_EDGE_ID` | `fieldbus-1` | Edge identifier (fieldbus/edge recipes) |
| `OPENFDD_MQTT_HOST` | — | Broker hostname (required for `edge`) |
| `OPENFDD_MQTT_ENABLED` | `1` (`0` for csv) | Toggle MQTT ingest on central |
| `OPENFDD_EDGE_KIT_DIR` | — | Provisioning kit path (required for `edge`) |
| `OPENFDD_JWT_SECRET` | — | Enable UI login; pair with `OPENFDD_ADMIN_PASSWORD` |
| `OPENFDD_ADMIN_PASSWORD` | — | admin/operator/viewer password when JWT is set |
| `OPENFDD_UI_BIND` | `0.0.0.0` | UI bind address (LAN access) |

Pin a build by SHA across a recipe:

```bash
OPENFDD_IMAGE_TAG=sha-abc1234 ./scripts/openfdd_stack_up.sh standalone
```
