# Central + fieldbus atomic cutover runbook

Open-FDD deploys **atomically** from the legacy monolithic edge to the four-container MQTTS stack. There is no transitional HTTP field-ingest or duplicate BACnet runtime. Use this document for cutover rehearsal and rollback.

## Rollback unit

Keep two artifacts from the pre-cutover environment:

1. **Workspace backup tarball** — `scripts/migrate/backup_pre_cutover.sh` writes `backups/pre-cutover-<timestamp>.tar.gz` plus optional migration sidecars and an image-tag manifest.
2. **Immutable GHCR image tags** — pin all four new-stack images (or the previous `openfdd-edge-rust` tag) to the same `sha-<git-sha>` recorded before cutover. See `docker/VERSION_MANIFEST.md`.

Rollback = restore tarball + redeploy previous image tags. Do not advance `nightly` until standalone MQTTS smoke passes on the candidate SHA.

## Pre-cutover checklist

Run in order on the production or staging host:

```bash
cd /path/to/open-fdd

# 1. Backup workspace + driver_tree/assignments sidecars
./scripts/migrate/backup_pre_cutover.sh

# 2. Dry-run driver tree → fieldbus migration report
./scripts/migrate/dry_run_migration_report.sh
# Review reports/migration-report.json — resolve fatal 599999 conflicts before cutover

# 3. Pass all gates (contracts, architecture, MQTT security, compose smoke)
./scripts/gates/run_all_gates.sh

# 4. Optional E2E rehearsal (Docker required for full path)
./scripts/gates/e2e_mqtts_smoke.sh
# Follow scripts/gates/e2e_mqtts_feather.md for Feather/FDD/UI/ack validation
```

## Atomic cutover procedure

1. **Stop legacy stack** — monolithic edge / `compose.edge.rust.yml` / any process binding UDP 47808 outside fieldbus.
2. **Apply fieldbus config** — merge migration TOML into `config/fieldbus/field_devices.toml`; verify hosted `objects.csv` for device 599999.
3. **Provision MQTT** — `cargo run -p openfdd_mqtt --bin openfdd-provision -- edge` for each edge; central subscriber kit under `deploy/mqtt/kits/<site>__central/`.
4. **Pin images** — export coordinated tags:

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-<sha>
export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:sha-<sha>
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-<sha>
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-<sha>
```

5. **Start new stack** — standalone (all-in-one) or split central + remote edge:

```bash
# Standalone (dev / single host)
docker compose -f docker/compose.standalone.yml up -d

# Central only
docker compose -f docker/compose.central.yml up -d

# Remote edge (outbound 8883 only)
export OPENFDD_MQTT_HOST=mqtt.your-central.example.com
export OPENFDD_EDGE_KIT_DIR=/path/to/deploy/mqtt/kits/<site>__<edge>
docker compose -f docker/compose.edge.yml up -d
```

6. **Verify** — ingest stats, Feather files, FDD status, UI login, command ack (see `scripts/gates/e2e_mqtts_feather.md`).

## Rollback procedure

```bash
# Stop new stack
docker compose -f docker/compose.standalone.yml down
docker compose -f docker/compose.central.yml down
docker compose -f docker/compose.edge.yml down

# Restore workspace from pre-cutover tarball
tar -xzf backups/pre-cutover-<timestamp>.tar.gz -C /path/to/parent-of-workspace

# Restore previous images (from backup manifest or your records)
source backups/pre-cutover-<timestamp>-image-tags.env
# Or legacy:
export OPENFDD_EDGE_RUST_IMAGE=ghcr.io/bbartling/openfdd-edge-rust:sha-<previous>

# Start previous stack and confirm historian + UI parity
```

## Environment variables

### MQTT (central + fieldbus)

| Variable | Service | Description |
|----------|---------|-------------|
| `OPENFDD_MQTT_ENABLED` | central, fieldbus | `1` to enable MQTTS bridge / ingest |
| `OPENFDD_MQTT_HOST` | central, fieldbus | Broker hostname (`mqtt` in compose, public host for remote edge) |
| `OPENFDD_MQTT_PORT` | central, fieldbus | Default `8883` (MQTTS) |
| `OPENFDD_MQTT_CA_PEM` | central, fieldbus | Path to broker CA cert inside container (e.g. `/mqtt/ca.pem`) |
| `OPENFDD_MQTT_CERT_PEM` | central, fieldbus | Client cert (`central.cert.pem` or `edge.cert.pem`) |
| `OPENFDD_MQTT_KEY_PEM` | central, fieldbus | Client private key |
| `OPENFDD_MQTT_SPOOL_DIR` | fieldbus | Durable outbound spool directory |
| `OPENFDD_SITE_ID` | central, fieldbus | Site identifier in topic prefix |
| `OPENFDD_EDGE_ID` | fieldbus | Edge identifier; central may use `+` wildcard subscriber |

### Central API / auth

| Variable | Description |
|----------|-------------|
| `OPENFDD_WORKSPACE` | Historian, model, and FDD data root (default `/workspace`) |
| `OPENFDD_JWT_SECRET` | HS256 secret; when set, all `/api/*` routes except health require `Authorization: Bearer <JWT>` |
| JWT claims | `sub`, `role` (`viewer` \| `operator` \| `admin`); commands need `operator` or `admin` |

### Fieldbus local admin

| Variable | Description |
|----------|-------------|
| `OPENFDD_FIELDBUS_CONFIG_DIR` | Config mount (default `/app/config`) |
| `OPENFDD_FIELDBUS_HTTP_HOST` | Local Swagger bind (default `127.0.0.1`) |
| `OPENFDD_FIELDBUS_HTTP_PORT` | Local admin port (default `8081`) |

### Image pins (compose)

| Variable | Image |
|----------|-------|
| `OPENFDD_CENTRAL_IMAGE` | `ghcr.io/bbartling/openfdd-central` |
| `OPENFDD_UI_IMAGE` | `ghcr.io/bbartling/openfdd-ui` |
| `OPENFDD_FIELDBUS_IMAGE` | `ghcr.io/bbartling/openfdd-fieldbus` |
| `OPENFDD_MQTT_IMAGE` | `ghcr.io/bbartling/openfdd-mqtt` |

### Migration / backup

| Variable | Description |
|----------|-------------|
| `OPENFDD_WORKSPACE_PATH` | Override workspace path for `backup_pre_cutover.sh` |
| `OPENFDD_BACKUP_DIR` | Backup output directory (default `backups/`) |
| `OPENFDD_DRIVER_TREE` | Path to `driver_tree.json` for dry-run migration |
| `OPENFDD_MIGRATION_REPORT_DIR` | Report output dir (default `reports/`) |

## Gate reference

| Gate | Script |
|------|--------|
| No central BACnet wire deps | `scripts/gates/architecture_no_central_fieldwire.sh` |
| MQTT contract tests | `scripts/gates/mqtt_contract_unit.sh` |
| Central OpenAPI present | `scripts/gates/openapi_central_present.sh` |
| No anonymous MQTT | `scripts/gates/no_anonymous_mqtt.sh` |
| Sole UDP 47808 owner | `scripts/gates/sole_bacnet_udp_owner.sh` |
| Standalone compose smoke | `scripts/release/smoke_standalone_mqtts.sh` |
| All gates | `scripts/gates/run_all_gates.sh` |

## Known gaps after cutover

- **Live OT BACnet** — validate on bench hardware with `scripts/fieldbus/bench_test.sh`; not part of default CI gates.
- **Selenium UI rig** — `tests/selenium/` covers legacy flows; extend for central edge-shadow pages.
- **Modbus/Haystack migration** — `dry_run_migration_report.sh` flags manual mapping; configure in `config/fieldbus/` per report `unresolved[]`.
- **Full Docker E2E in CI** — `e2e_mqtts_smoke.sh` validates compose + gates; full Feather/FDD/UI path is `DOCKER_REQUIRED` locally.

## Related docs

- `deploy/mqtt/README.md` — certificate provisioning
- `docker/VERSION_MANIFEST.md` — coordinated image tags
- `scripts/gates/e2e_mqtts_feather.md` — compose E2E sequence
