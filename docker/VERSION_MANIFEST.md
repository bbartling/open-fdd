# Open-FDD multi-image version manifest

All four container images in the MQTT stack share a **coordinated release** tied to the Cargo workspace version in the repository root `Cargo.toml` (`[workspace.package].version`).

## Images

| Image | Dockerfile | Role |
|-------|------------|------|
| `ghcr.io/bbartling/openfdd-central` | `services/central/Dockerfile` | MQTTS ingest, Feather, FDD, REST + OpenAPI |
| `ghcr.io/bbartling/openfdd-ui` | `workspace/dashboard/Dockerfile` | React operator dashboard (static + Caddy) |
| `ghcr.io/bbartling/openfdd-fieldbus` | `services/fieldbus/Dockerfile` | BACnet/Modbus/Haystack edge + local Swagger |
| `ghcr.io/bbartling/openfdd-mqtt` | `services/mqtt/Dockerfile` | Mosquitto MQTTS broker |

## Tags (`.github/workflows/ghcr-openfdd-stack.yml`)

| Tag | When | Purpose |
|-----|------|---------|
| `sha-<7-char-git-sha>` | Every publish | Immutable rollback unit |
| `<workspace.version>` | Every publish | Semver from `Cargo.toml` (e.g. `3.3.0`) |
| `nightly` | `master` branch only | Floating integration channel |

Current stack publish builds **linux/amd64** only so RocksDB-heavy central/fieldbus images finish within GH Actions time budgets (QEMU arm64 previously timed out at 2h). Re-enable multi-arch when a native arm64 runner or longer budget is available.

Only advance `nightly` after `scripts/release/smoke_standalone_mqtts.sh` passes on the candidate SHA.

## Compose alignment

`docker/compose.standalone.yml`, `docker/compose.central.yml`, and `docker/compose.edge.yml` default to `:nightly` image tags. Pin all four services to the same `sha-*` or semver tag for production:

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-abc1234
export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:sha-abc1234
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-abc1234
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-abc1234
```

## Version source of truth

1. **Cargo workspace** — `[workspace.package].version` in `/Cargo.toml` (used by GHCR workflow).
2. **VERSION file** — human-facing release label (may include pre-release suffix, e.g. `3.3.0-beta.1`).
3. **Per-crate `Cargo.toml`** — individual crates inherit workspace version; keep in sync via `cargo workspaces` or manual bump.

Bump all three together when cutting a coordinated stack release.

## Legacy

`ghcr.io/bbartling/openfdd-edge-rust` (monolithic bridge image) is a separate lineage published by `rust-ghcr.yml`. It is not part of this four-image manifest and is superseded by the split stack for new deployments.
