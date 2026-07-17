# Central + fieldbus deployment runbook

Open-FDD is a four-container MQTTS stack (`openfdd-central`, `openfdd-ui`,
`openfdd-fieldbus`, `openfdd-mqtt`) plus the slim `openfdd-mcp` server. Central
never touches the BACnet wire — `fieldbus` is the sole BACnet/IP runtime and
publishes to central over MQTTS. This runbook covers deploying, pinning, and
rolling back a site.

For the recipe/env matrix see [Build recipes](operations/build-recipes.md).

## Backup + pin (before any change)

Keep two artifacts so you can roll back a change:

1. **Workspace backup tarball** — `scripts/migrate/backup_pre_cutover.sh` writes
   `backups/pre-cutover-<timestamp>.tar.gz` plus optional migration sidecars and
   an image-tag manifest.
2. **Immutable GHCR image tags** — pin all stack images to the same
   `sha-<git-sha>`. See `docker/VERSION_MANIFEST.md`.

Do not advance `nightly` until the standalone MQTTS smoke passes on the
candidate SHA.

## Pre-deploy checklist

Run in order on the production or staging host:

```bash
cd /path/to/open-fdd

# 1. Backup workspace + driver_tree/assignments sidecars
./scripts/migrate/backup_pre_cutover.sh

# 2. Dry-run driver tree → fieldbus config report
./scripts/migrate/dry_run_migration_report.sh
# Review reports/migration-report.json — resolve fatal 599999 conflicts first

# 3. Pass all gates (contracts, architecture, MQTT security, compose smoke)
./scripts/gates/run_all_gates.sh

# 4. Optional E2E rehearsal (Docker required for full path)
./scripts/gates/e2e_mqtts_smoke.sh
# Follow scripts/gates/e2e_mqtts_feather.md for Feather/FDD/UI/ack validation
```

## Deploy procedure

1. **Apply fieldbus config** — set `config/fieldbus/field_devices.toml`; verify
   hosted `objects.csv` for device 599999.
2. **Provision MQTT** — `cargo run -p openfdd_mqtt --bin openfdd-provision -- edge`
   for each edge; central subscriber kit under `deploy/mqtt/kits/<site>__central/`.
3. **Pin images** — export coordinated tags (or set `OPENFDD_IMAGE_TAG`):

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-<sha>
export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:sha-<sha>
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-<sha>
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-<sha>
```

4. **Start the stack** — standalone (all-in-one) or split central + remote edge:

```bash
# Standalone (dev / single host)
./scripts/openfdd_stack_up.sh standalone

# Central only
./scripts/openfdd_stack_up.sh central

# Remote edge (outbound 8883 only)
export OPENFDD_MQTT_HOST=mqtt.your-central.example.com
export OPENFDD_SITE_ID=<site>
export OPENFDD_EDGE_KIT_DIR=/path/to/deploy/mqtt/kits/<site>__<edge>
./scripts/openfdd_stack_up.sh edge
```

5. **Verify** — ingest stats, Feather files, FDD status, UI login, command ack
   (see `scripts/gates/e2e_mqtts_feather.md`).

## Rollback procedure

```bash
# Stop the stack
docker compose -f docker/compose.standalone.yml down
docker compose -f docker/compose.central.yml down
docker compose -f docker/compose.edge.yml down

# Restore workspace from the backup tarball
tar -xzf backups/pre-cutover-<timestamp>.tar.gz -C /path/to/parent-of-workspace

# Restore previous pinned images and restart
source backups/pre-cutover-<timestamp>-image-tags.env
OPENFDD_IMAGE_TAG=<previous-sha> ./scripts/openfdd_stack_up.sh standalone
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
| `OPENFDD_MCP_IMAGE` | `ghcr.io/bbartling/openfdd-mcp` |

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

## Known gaps

- **Live OT BACnet** — validate on bench hardware with `scripts/fieldbus/bench_test.sh`; not part of default CI gates.
- **Modbus/Haystack config** — `dry_run_migration_report.sh` flags manual mapping; configure in `config/fieldbus/` per report `unresolved[]`.
- **Full Docker E2E in CI** — `e2e_mqtts_smoke.sh` validates compose + gates; full Feather/FDD/UI path is `DOCKER_REQUIRED` locally.

## Related docs

- `deploy/mqtt/README.md` — certificate provisioning
- `docker/VERSION_MANIFEST.md` — coordinated image tags
- `scripts/gates/e2e_mqtts_feather.md` — compose E2E sequence
