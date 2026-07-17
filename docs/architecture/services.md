---
title: Services
parent: Architecture
nav_order: 1
---

# Stack services

Open-FDD runs as a small set of GHCR images composed per recipe. See
[Build recipes](../operations/build-recipes.md) for which images each recipe pulls.

```text
ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-ui:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-fieldbus:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mqtt:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-nightly}
```

## Containers

| Container | Image | Role |
|-----------|-------|------|
| `central` | `openfdd-central` | REST API (`:8080`), JWT auth, historian, DataFusion FDD engine, reports, MCP API surface |
| `ui` | `openfdd-ui` | Caddy static React dashboard (`:3000`), proxies `/api` to central |
| `fieldbus` | `openfdd-fieldbus` | BACnet/IP poll (`network_mode: host`), publishes over MQTTS |
| `mqtt` | `openfdd-mqtt` | Mosquitto broker, MQTTS on `:8883` |
| `mcp` | `openfdd-mcp` | Slim Rust MCP server for external agents |

```text
┌──────────────────────┐        ┌──────────────────────────────┐
│ ui (Caddy :3000)     │──/api─▶│ central (:8080)              │
└──────────────────────┘        │ REST · JWT · historian · FDD │
                                 └──────────────────────────────┘
                                          ▲ MQTTS (8883)
                                          │
              ┌───────────────────────────┴───────────────┐
              │ mqtt (Mosquitto)                            │
              └───────────────────────────▲─────────────────┘
                                          │ MQTTS haystack kv
                                 ┌────────┴─────────┐
                                 │ fieldbus (BACnet)│
                                 └──────────────────┘
```

## MCP server

`openfdd-mcp` is a slim Rust image that talks to central over
`OPENFDD_API_BASE` (default `http://central:8080`):

```bash
docker run --rm -i \
  -e OPENFDD_API_BASE=http://central:8080 \
  ghcr.io/bbartling/openfdd-mcp:latest
```

See [MCP & agents](../mcp-agents/mcp.md).

## Workspace

All durable site state lives under `workspace/` (bind-mounted into central).
Never delete it.
