# Open-FDD multi-image version manifest

All container images in the MQTT / CSV stack share a **coordinated release** tied to the Cargo workspace version in the repository root `Cargo.toml` (`[workspace.package].version`).

## Images

| Image | Dockerfile | Role |
|-------|------------|------|
| `ghcr.io/bbartling/openfdd-central` | `services/central/Dockerfile` | MQTTS ingest, Feather, FDD, REST + OpenAPI |
| `ghcr.io/bbartling/openfdd-ui` | `services/ui/Dockerfile` | Streamlit vibe19 lab (Feather + SQL FDD) |
| `ghcr.io/bbartling/openfdd-fieldbus` | `services/fieldbus/Dockerfile` | BACnet/Modbus/Haystack edge + local Swagger |
| `ghcr.io/bbartling/openfdd-mqtt` | `services/mqtt/Dockerfile` | Mosquitto MQTTS broker |
| `ghcr.io/bbartling/openfdd-mcp` | `Dockerfile.mcp` | Optional MCP stdio sidecar → central |

## Tags

| Tag | When | Purpose |
|-----|------|---------|
| `sha-<7-char-git-sha>` | Every publish | Immutable rollback unit |
| `<workspace.version>` | Every publish | Semver from `Cargo.toml` |
| `nightly` | `master` branch only | Floating integration channel |

Stack publish builds **linux/amd64**. MCP also publishes multi-arch. Re-enable stack multi-arch when a native arm64 runner is available.

Only advance `nightly` after recipe file smoke (`scripts/release/smoke_standalone_mqtts.sh`) passes on the candidate SHA.

## Compose alignment

`docker/compose.standalone.yml`, `docker/compose.central.yml`, `docker/compose.edge.yml`, and `docker/compose.csv.yml` default to `:nightly`. Pin services to the same `sha-*` or semver tag for production:

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-abc1234
export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:sha-abc1234
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-abc1234
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-abc1234
export OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:sha-abc1234
```

## Version source of truth

1. **Cargo workspace** — `[workspace.package].version` in `/Cargo.toml`.
2. **VERSION file** — human-facing release label.
3. **Per-crate `Cargo.toml`** — inherit workspace version.

Bump all three together when cutting a coordinated stack release.

## Latest verified nightlies

Published successfully from soak-P0 tip **`884aaed6`** (merge #565 — JWT + confirm_min + aliases):

| Images | Immutable tag | Workflow |
|--------|---------------|----------|
| `openfdd-central`, `openfdd-ui`, `openfdd-fieldbus`, `openfdd-mqtt` | `sha-884aaed` | [29776327547](https://github.com/bbartling/open-fdd/actions/runs/29776327547) — success |
| `openfdd-mcp` | `sha-884aaed` | [29776326354](https://github.com/bbartling/open-fdd/actions/runs/29776326354) — success |

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-884aaed
export OPENFDD_UI_IMAGE=ghcr.io/bbartling/openfdd-ui:sha-884aaed
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-884aaed
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-884aaed
export OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:sha-884aaed
# or OPENFDD_IMAGE_TAG=sha-884aaed / :nightly (same digest as of 2026-07-20 publish)
```

UI is Streamlit (`services/ui`); FDD operator path is central DataFusion SQL.
When `OPENFDD_JWT_SECRET` is set, also set `OPENFDD_ADMIN_PASSWORD` (or
`OPENFDD_API_TOKEN`) on **both** central and ui so Run Rules / package ingest
can authenticate.

Workspace Cargo version remains **3.3.0** (no semver bump for this integration tip —
nightlies key off `sha-*`). Bump workspace + `VERSION` together only when cutting a
coordinated release.

**Human Workbench gate** still required before BACnet OT PASS (hosted **599999** discoverability). See `docs/agent/linux-edge-tester-stack-recipes-prompt.md`.
