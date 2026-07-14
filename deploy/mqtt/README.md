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
│   └── server.key.pem
├── kits/                  # generated edge kits — gitignored
│   └── {site_id}__{edge_id}/
│       ├── ca.pem         # public CA only (copy of ca/ca.pem)
│       ├── edge.cert.pem
│       ├── edge.key.pem
│       ├── edge.json      # broker URL, site/edge IDs, cert paths
│       └── mosquitto.acl  # ACL snippet — merge into broker config
└── mosquitto.acl          # optional merged ACL for the broker
```

## Provision an edge kit

```bash
cargo run -p openfdd_mqtt --bin openfdd-provision -- edge \
  --site-id lab \
  --edge-id fieldbus-1 \
  --broker-host mqtt.example.com \
  --out-dir ./deploy/mqtt
```

The edge kit contains **only** the public `ca.pem` plus edge client cert/key. The CA private key stays under `deploy/mqtt/ca/` and must never be copied to remote edges.

## Broker setup

1. Generate or reuse CA under `deploy/mqtt/ca/`.
2. Place Mosquitto server certificates in `deploy/mqtt/certs/` (or your chosen path).
3. Copy or merge the kit's `mosquitto.acl` into the broker ACL file referenced by `services/mqtt/mosquitto.conf`.
4. Bind-mount `ca.pem`, server certs, and ACL into the `openfdd-mqtt` container at runtime.

## Edge runtime

Mount the generated kit at `/mqtt` (read-only) and set:

- `OPENFDD_MQTT_ENABLED=1`
- `OPENFDD_SITE_ID` / `OPENFDD_EDGE_ID` matching the kit
- `OPENFDD_MQTT_CA_PEM=/mqtt/ca.pem`
- `OPENFDD_MQTT_CERT_PEM=/mqtt/edge.cert.pem`
- `OPENFDD_MQTT_KEY_PEM=/mqtt/edge.key.pem`

Outbound TCP **8883** (MQTTS) is the only required central connectivity from the edge.
