# OT edge — unmaintained

Archived. Unmaintained. Not built or tested by CI. Not published to GHCR.

This tree is the BACnet, Modbus, Haystack wire, fieldbus gateway, Mosquitto broker, and edge process that used to live on the product path. History is preserved with `git mv`.

| Path | Was |
| --- | --- |
| `services/fieldbus` | BACnet / Modbus / Haystack field containers |
| `services/mqtt` | Mosquitto MQTTS broker image |
| `config/fieldbus` | Gateway and device config |
| `deploy/mqtt` | Broker ACL example and kit layout |
| `docker/compose.*.yml` | Edge, fieldbus, and standalone OT recipes |
| `edge/src/drivers` | Protocol clients (the product `edge/` crate no longer links them) |
| `edge/src/main.rs`, `server.rs`, `bin/` | Edge process and edge CLI |
| `tests/integration/bacpypes3` | BACpypes3 container integration test |
| `ci/` | Former BACnet/MQTT and Wave C workflows (not executed from here) |
| `scripts/nightly-ot-bench` | OT bench scripts |
| `scripts/gates` | MQTT/BACnet guard gates and MQTTS smokes |
| `scripts/release/smoke_standalone_mqtts.sh` | Standalone MQTTS file smoke |
| `crates/openfdd_mqtt` | Central MQTT client, spool, and edge-kit provisioner |
| `crates/openfdd_connector_runtime` | Field connector auth and telemetry sink |
| `services/central/src/mqtt_monitor.rs` | `/api/mqtt/*` monitor and edge-kit route |
| `services/central/src/ingest.rs` | MQTT subscriber copied from the product before it was removed |
| `scripts/security` | Broker ACL observer, field-only exposure lint, OT compose selection |
| `tests/security` | CI unit tests that covered those checks |

The checksummed pin of commit `cdaa4f15` remains at [`../unqualified-cdaa4f15/`](../unqualified-cdaa4f15/README.md). Do not treat that snapshot and this tree as interchangeable: this tree is newer and is the one to read. The snapshot's `source/` and `CHECKSUMS.sha256` stay frozen.

## What still runs in the product

Nothing in this tree. Product ingest is the Normal Framework portal API and CSV packages. `crates/openfdd_mqtt` and `crates/openfdd_connector_runtime` are archived here and are not Cargo workspace members.

The product semantic library remains `edge/` (package ingest, Haystack/Brick role tags, SQL FDD helpers). It does not include protocol drivers or an edge process. Do not rebuild the Railway MQTT broker from this tree.

## Restore

Isolated render of the pinned images (no containers, no database):

```bash
export OPENFDD_OT_ARCHIVE_RESTORE=1
./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
```

Building these Dockerfiles or compose files is manual and unsupported. Do not add them back to the Cargo workspace, GHCR publish matrix, or product compose recipes.
