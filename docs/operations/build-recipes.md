---
title: Build recipes
parent: Operations
nav_order: 2
nav_exclude: true

---

# Build recipes

Open-FDD uses the same GHCR images for both cloud-lab and self-hosted deployments. For most users there are two recommended deployment paths:

| Deployment | Best for | Services | Guide |
| --- | --- | --- | --- |
| **Railway cloud lab** | demos, CSV/package evaluation, temporary cloud access | `openfdd-central` + `openfdd-web` | [Railway deployment](RAILWAY_DEPLOYMENT.md) |
| **Behind-firewall VM** | IT-managed dashboard on LAN/VPN | `openfdd-central` + `openfdd-web` via Compose `csv` | [VM deployment](VM_DEPLOYMENT.md) |

Both paths consume the same container artifacts. `nightly` is the floating green-master channel; `sha-<7>` is the preferred reproducible deployment pin.

For OT/BACnet deployments, use the additional fieldbus/MQTT recipes only when the host/network topology deliberately provides OT access.

## Images

| Image | Role |
|-------|------|
| `ghcr.io/bbartling/openfdd-central` | API + FDD engine (DataFusion rule registry) |
| `ghcr.io/bbartling/openfdd-web` | React engineering UI (container port `8080`; local Compose maps host `3000`) |
| `ghcr.io/bbartling/openfdd-fieldbus` | BACnet/IP poller, publishes over MQTTS |
| `ghcr.io/bbartling/openfdd-bacnet-modbus` | Split BACnet edge process (`bacnet-modbus` Docker target) |
| `ghcr.io/bbartling/openfdd-haystack` | Split outbound Haystack HTTP edge process (`haystack` Docker target) |
| `ghcr.io/bbartling/openfdd-mqtt` | Mosquitto broker (MQTTS on 8883) |
| `ghcr.io/bbartling/openfdd-mcp` | Slim Rust MCP server (talks to central) |

All release images are intended to be publicly pullable from GHCR so an IT department, Railway, or a local Docker host does not need a repository credential just to run Open-FDD. Package visibility is a GitHub Package setting and should be checked whenever a new GHCR package name is introduced.

See [Release channels](release-channels.html) and [GHCR images](ghcr-images.html).

## Local Compose recipes at a glance

| Recipe | Compose file | Services | Use |
|--------|--------------|----------|-----|
| `csv` | `docker/compose.csv.yml` | central + web (`OPENFDD_MQTT_ENABLED=0`) | **Recommended IT dashboard / CSV-package deployment** |
| `standalone` | `docker/compose.standalone.yml` | mqtt + central + web + fieldbus | single OT-connected host |
| `central` | `docker/compose.central.yml` | mqtt + central + web | hub for remote fieldbus edges |
| `edge` | `docker/compose.edge.yml` | fieldbus only | remote OT edge |
| `edge-split` | `docker/compose.edge.split.yml` | BACnet/Modbus + optional Haystack | migrating OT edge |

The `central` and `csv` recipes contain no fieldbus service and never start a
BACnet/Modbus/Haystack process. Use `edge` or `standalone` when the host is
deliberately connected to an OT network. This separation is a deployment
boundary, not a runtime capability flag.

The split migration recipe builds separate final targets from the Rust package:
`bacnet-modbus` contains only `openfdd-bacnet-modbus`, `haystack` contains only
`openfdd-haystack`, and the default `compatibility` target contains only the
legacy `openfdd-fieldbus`. The `bacnet-modbus` service uses host networking for
BACnet UDP; the optional `haystack` service has no host network, binds
`0.0.0.0` only inside its container, publishes to a host loopback port, and
requires both an API key and an explicit outbound HTTP(S) endpoint at startup.
The inactive profile can resolve without an endpoint, but the Haystack process
rejects a blank endpoint. Do not
replace either entrypoint with a runtime profile flag. The recipe is a
source/build checkpoint; no GHCR publication or live OT qualification is
claimed here.

The `central` and `csv` recipes contain no fieldbus service and never start a
BACnet/Modbus/Haystack process. Use `edge` or `standalone` when the host is
deliberately connected to an OT network. This separation is a deployment
boundary, not a runtime capability flag.

## Bring a recipe up

`openfdd_stack_up.sh` pulls the GHCR images for the recipe (unless
`--no-pull`/`--build`), runs `docker compose up -d`, and waits on
`GET /api/health` (except the `edge` recipe):

```bash
# Recommended behind-firewall dashboard
export OPENFDD_IMAGE_TAG=nightly
export OPENFDD_JWT_SECRET='replace-with-a-long-random-secret'
export OPENFDD_ADMIN_PASSWORD='replace-with-a-strong-password'
./scripts/openfdd_stack_up.sh csv

# OT-connected alternatives
./scripts/openfdd_stack_up.sh standalone
./scripts/openfdd_stack_up.sh central
OPENFDD_MQTT_HOST=hub.example.com \
OPENFDD_SITE_ID=site-a \
OPENFDD_EDGE_KIT_DIR=./deploy/mqtt/kits/site-a__fieldbus-1 \
  ./scripts/openfdd_stack_up.sh edge

# Developer-only local source build instead of pulling GHCR:
./scripts/openfdd_stack_up.sh csv --build
```

Pull without starting:

```bash
./scripts/openfdd_stack_pull.sh csv   # or standalone|central|edge|mcp|all
```

After `csv` boot: UI on `http://<host>:3000`, API health on `http://<host>:8080/api/health`.

## Recipes in detail

### csv — recommended dashboard / CSV-package deployment

`central + web` with `OPENFDD_MQTT_ENABLED=0`. No broker or fieldbus images are required. This is the cleanest recipe for an IT department hosting Open-FDD as a dashboard VM behind its firewall, and it is also the local equivalent of the Railway minimal cloud-lab topology.

```bash
./scripts/openfdd_stack_up.sh csv
```

The Compose recipe persists central state in the repository `workspace/` directory. For an IT-managed VM, back up that directory and prefer an immutable `sha-*` image tag after qualification.

Full VM guide: [VM deployment](VM_DEPLOYMENT.md).

### standalone — everything on one OT-connected host

`mqtt + central + web + fieldbus`. The all-on-edge box: BACnet polling,
broker, engine, and UI on a single machine. `fieldbus` runs on the host
network for BACnet/IP.

```bash
./scripts/openfdd_stack_up.sh standalone
```

The fieldbus service mounts the named `fieldbus-state` volume at
`/edge-state`. The opt-in priority history scheduler uses that volume for its
durable cursor and bounded P1–P16 snapshots. It is disabled by default. To
enable it, provide a trusted field-device catalog and set:

```bash
OPENFDD_PRIORITY_SCAN_ENABLED=1 \
OPENFDD_PRIORITY_SCAN_INTERVAL_SECS=3600 \
OPENFDD_PRIORITY_SCAN_MAX_POINTS_PER_DEVICE=100 \
./scripts/openfdd_stack_up.sh standalone
```

The scheduler visits one configured device after a delay following each
completed visit, defaults to one hour, enforces a five-minute minimum, and
does not catch up after a restart. It reads only configured points and never
performs discovery, writes, priority releases, or remediation. The edge
history endpoint is `POST /api/connector/priority-history`; the authenticated
central projection is `POST /api/connectors/{edge_id}/priority-history`.
Operators and admins can request one bounded visit through
`POST /api/connectors/{edge_id}/priority-history/trigger`; viewers are denied
before the edge proxy is contacted. The trigger shares the scheduler's
non-overlap guard and does not bypass the explicit enable flag.

History is retained on the edge in an append-only, fsynced JSONL journal with
bounded checkpoint compaction. Torn trailing lines are repaired on restart;
corrupt non-tail state disables history fail-closed while core BACnet polling
continues. Cursors cannot address beyond the retained 100,000-record window;
page traversal stops after the requested offset, page, and one continuation
probe. The cloud recipes do not create an edge store or scanner.

### central — hub for remote edges

`mqtt + central + web`. Run the hub on a local server or private infrastructure; remote fieldbus edges attach over MQTTS with the `edge` recipe.

```bash
./scripts/openfdd_stack_up.sh central
```

### edge — fieldbus attach

`fieldbus` only, host networking for BACnet/IP, needs outbound TCP 8883 to a
central broker. Required env: `OPENFDD_MQTT_HOST`, `OPENFDD_SITE_ID`,
`OPENFDD_EDGE_KIT_DIR` (path to the provisioning kit for this edge).

The edge recipe also mounts `fieldbus-state` at `/edge-state` so a restart
does not reset the stable device cursor or discard retained history. History is
edge-local in this phase. MQTT history synchronization is a separate future
contract; the cloud service does not invent HTTP-over-MQTT and does not boot a
fieldbus scanner.

```bash
OPENFDD_MQTT_HOST=hub.example.com \
OPENFDD_SITE_ID=site-a \
OPENFDD_EDGE_KIT_DIR=./deploy/mqtt/kits/site-a__fieldbus-1 \
  ./scripts/openfdd_stack_up.sh edge
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
| `OPENFDD_CENTRAL_BIND` | `0.0.0.0` | Central host bind; use `127.0.0.1` on a dashboard VM unless direct API access is needed |
| `OPENFDD_WEB_BIND` | `0.0.0.0` | React web host bind (LAN/VPN access) |
| `OPENFDD_CENTRAL_UPSTREAM` | `central:8080` | Runtime web proxy target; Railway uses private service DNS |
| `OPENFDD_PRIORITY_SCAN_ENABLED` | `0` | Explicitly enable the read-only edge priority history scheduler |
| `OPENFDD_PRIORITY_SCAN_INTERVAL_SECS` | `3600` | Delay after each completed device visit; minimum `300` |
| `OPENFDD_PRIORITY_SCAN_MAX_POINTS_PER_DEVICE` | `100` | Bound configured points visited per device cycle; maximum `1000` |
| `OPENFDD_EDGE_STORE_DIR` | `/edge-state` in fieldbus recipes | Durable edge store root; do not mount this into central/cloud |

Pin a build by SHA across a recipe:

```bash
OPENFDD_IMAGE_TAG=sha-abc1234 ./scripts/openfdd_stack_up.sh csv
```
