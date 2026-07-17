# Release channels

Open-FDD uses separate channels for automated nightly builds and manual promoted releases. Every stack image moves together on the same channel tags.

## Channels

| Tag | Source | Trigger | Mutable |
| --- | --- | --- | --- |
| `nightly` | `ghcr-openfdd-stack.yml` | push to `master`, daily cron, manual | yes |
| `sha-<short>` | `ghcr-openfdd-stack.yml` | same as nightly | no (immutable reference) |
| `nightly-YYYYMMDD` | `ghcr-openfdd-stack.yml` | same as nightly | optional date stamp |
| `beta` | stack release workflow | manual `workflow_dispatch` | yes until next beta |
| `stable` | stack release workflow | manual `workflow_dispatch` | yes until next stable |
| semver (e.g. `3.3.0`) | stack release workflow | manual | immutable release |

## Images

```
ghcr.io/bbartling/openfdd-central
ghcr.io/bbartling/openfdd-ui
ghcr.io/bbartling/openfdd-fieldbus
ghcr.io/bbartling/openfdd-mqtt
ghcr.io/bbartling/openfdd-mcp
```

`OPENFDD_IMAGE_TAG` picks the channel for a recipe. Which images a recipe pulls is in [Build recipes](../operations/build-recipes.md).

## What nightly includes

The container stack:

- `openfdd-central` — HTTP API at `/api/*` and the FDD engine
- `openfdd-ui` — Caddy serving the compiled React dashboard, proxying `/api` to central
- `openfdd-fieldbus` — BACnet/IP poller publishing over MQTTS
- `openfdd-mqtt` — Mosquitto broker
- `openfdd-mcp` — slim Rust MCP server

## Operator guidance

- **Development / CI validation:** pin `OPENFDD_IMAGE_TAG=sha-<commit>`.
- **Latest master:** `OPENFDD_IMAGE_TAG=nightly` (default).
- **Production pilot:** promote to `beta`, then `stable`.
