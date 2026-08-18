# Open-FDD multi-image version manifest

All container images in the MQTT / CSV stack share a **coordinated release** tied to the Cargo workspace version in the repository root `Cargo.toml` (`[workspace.package].version`).

## Images

| Image | Dockerfile | Role |
|-------|------------|------|
| `ghcr.io/bbartling/openfdd-central` | `services/central/Dockerfile` | MQTTS ingest, Feather, FDD, REST + OpenAPI |
| `ghcr.io/bbartling/openfdd-web` | `frontend/web/Dockerfile` | React SPA product UI (nginx → central `/api`) |
| `ghcr.io/bbartling/openfdd-fieldbus` | `services/fieldbus/Dockerfile` | BACnet/Modbus/Haystack edge + local Swagger |
| `ghcr.io/bbartling/openfdd-mqtt` | `services/mqtt/Dockerfile` | Mosquitto MQTTS broker |
| `ghcr.io/bbartling/openfdd-mcp` | `Dockerfile.mcp` | Optional MCP stdio sidecar → central |

## Tags

| Tag | When | Purpose |
|-----|------|---------|
| `sha-<7-char-git-sha>` | Every publish | Immutable rollback unit |
| `<workspace.version>` | Every publish | Semver from `Cargo.toml` |
| `<workspace.version>-n<run>` | Every publish | Extra nightly run pointer (e.g. `3.3.1-n42`) |
| `nightly` | `master` branch only | Floating integration channel |

Stack publish builds **linux/amd64**. MCP also publishes multi-arch. Re-enable stack multi-arch when a native arm64 runner is available.

Only advance `nightly` after recipe file smoke (`scripts/release/smoke_standalone_mqtts.sh`) passes on the candidate SHA.

## Compose alignment

`docker/compose.standalone.yml`, `docker/compose.central.yml`, `docker/compose.edge.yml`, and `docker/compose.csv.yml` default to `:nightly`. Pin services to the same `sha-*` or semver tag for production:

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-abc1234
export OPENFDD_WEB_IMAGE=ghcr.io/bbartling/openfdd-web:sha-abc1234
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

Published successfully from tip **`8850b0bf`** (merge #572 — Jobs contract; #571 audit):

| Images | Immutable tag | Workflow |
|--------|---------------|----------|
| `openfdd-central`, `openfdd-web`, `openfdd-fieldbus`, `openfdd-mqtt` | `sha-8850b0b` | [30176649928](https://github.com/bbartling/open-fdd/actions/runs/30176649928) — success |
| `openfdd-mcp` | `sha-8850b0b` | [30176649926](https://github.com/bbartling/open-fdd/actions/runs/30176649926) — success |

```bash
export OPENFDD_CENTRAL_IMAGE=ghcr.io/bbartling/openfdd-central:sha-8850b0b
export OPENFDD_WEB_IMAGE=ghcr.io/bbartling/openfdd-web:sha-8850b0b
export OPENFDD_FIELDBUS_IMAGE=ghcr.io/bbartling/openfdd-fieldbus:sha-8850b0b
export OPENFDD_MQTT_IMAGE=ghcr.io/bbartling/openfdd-mqtt:sha-8850b0b
export OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:sha-8850b0b
# or OPENFDD_IMAGE_TAG=sha-8850b0b / :nightly
```

Product UI is **React** (`frontend/web` / `openfdd-web`).  
Production FDD = DataFusion SQL (`sql_rules/`). Pandas cookbook stays as oracle (PyPI / vibe19).
WattLab dumps use `tools/wattlab_export/` from central.

Superset audit: `docs/migration/VIBE19_VIBE20_OPENFDD_AUDIT.md`.

Workspace Cargo version remains **3.3.1**. Displayed UI revision is `{semver}+{shortsha}` from central `/api/health`.

**Human Workbench gate** still required before BACnet OT PASS (hosted **599999**). See `docs/agent/linux-edge-tester-stack-recipes-prompt.md`.
