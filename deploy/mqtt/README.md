# Open-FDD MQTT provisioning layout

Default output directory for `openfdd-provision edge` is `./deploy/mqtt/`.

## Directory layout

```
deploy/mqtt/
├── README.md              # this file (tracked)
├── ca/                    # CA private material — gitignored, central-only
│   ├── ca.pem             # public CA certificate
│   └── ca.key.pem         # CA private key (never ship to edges)
├── certs/                 # broker server TLS — gitignored, bind-mount to Mosquitto
│   ├── server.cert.pem
│   ├── server.key.pem
│   └── acl                    # broker ACL (regular file, mode 0644)
├── kits/                  # generated edge kits — gitignored
│   └── {site_id}__{edge_id}/
│       ├── ca.pem         # public CA only (copy of ca/ca.pem)
│       ├── edge.cert.pem
│       ├── edge.key.pem
│       ├── edge.json      # broker URL, site/edge IDs, cert paths
│       └── mosquitto.acl  # ACL snippet — merge into broker config
```

## Provision an edge kit

### CLI

```bash
cargo run -p openfdd_mqtt --bin openfdd-provision -- edge \
  --site-id lab \
  --edge-id fieldbus-1 \
  --broker-host mqtt.example.com \
  --out-dir ./deploy/mqtt
```

### Central API / Operations UI (GHCR tip)

Authenticated operators can download the same kit as a ZIP (public PEMs + `edge.json` only — **never** `ca.key.pem`):

- `POST /api/mqtt/edge-kits` with JSON `{ "site_id", "edge_id", "broker_host?", "broker_port?" }`
- Operations → MQTT → **Download edge kit**
- Central must see CA material at `OPENFDD_MQTT_CA_DIR` (default `{OPENFDD_WORKSPACE}/deploy/mqtt/ca`)

Railway: mount CA (including `ca.key.pem`) on central’s private volume only; download the ZIP in the browser, then scp/mount onto on-prem fieldbus at `/mqtt`.

The edge kit contains **only** the public `ca.pem` plus edge client cert/key. The CA private key stays under `deploy/mqtt/ca/` and must never be copied to remote edges.

## Broker setup

1. Generate or reuse CA under `deploy/mqtt/ca/`.
2. Place Mosquitto server certificates in `deploy/mqtt/certs/` (or your chosen path).
3. Create the broker ACL as a regular file before first start, then copy or merge each kit's `mosquitto.acl` into it:
   `install -m 0644 deploy/mqtt/acl.example deploy/mqtt/certs/acl`.
4. Bind-mount `ca.pem`, server certs, and ACL into the `openfdd-mqtt` container at runtime.

The Compose stacks mount the complete `deploy/mqtt/certs/` directory at
`/mosquitto/certs`; Mosquitto reads `/mosquitto/certs/acl`. Do not create the
legacy `deploy/mqtt/acl/` directory or mount an ACL at `/mosquitto/config/acl`.
The image entrypoint assigns uid/gid 1883 read access while keeping
`server.key.pem` at mode 0600 or 0640.

## Edge runtime

Mount the generated kit at `/mqtt` (read-only) and set:

- `OPENFDD_MQTT_ENABLED=1`
- `OPENFDD_SITE_ID` / `OPENFDD_EDGE_ID` matching the kit
- `OPENFDD_MQTT_CA_PEM=/mqtt/ca.pem`
- `OPENFDD_MQTT_CERT_PEM=/mqtt/edge.cert.pem`
- `OPENFDD_MQTT_KEY_PEM=/mqtt/edge.key.pem`

Outbound TCP **8883** (MQTTS) is the only required central connectivity from the edge.

## Edge bandwidth

Fieldbus publishes one complete snapshot of every successfully polled point each
cycle. Stable fan, damper, valve and status values remain present in the
historian and reports; the edge never changes telemetry into a change-only feed.

| Env | Default (prod) | Effect |
|-----|----------------|--------|
| `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS` | 300 (min 60) | Decouple publish cadence from BACnet poll |
| `OPENFDD_POLL_HEALTH_ONLY=1` | off | Poll ~30% HVAC health roles (see [`BACNET_OT_POLICY.md`](../docs/operations/BACNET_OT_POLICY.md)) |

Rough sizing: a full snapshot is approximately **150–250 B × N points** per
cycle. On a constrained link, explicitly select the documented health-only poll
profile; do not suppress unchanged values after polling them.

Dev benches: `OPENFDD_FIELDBUS_DEV_FAST_POLL=1` allows faster poll/publish for OT gates.
