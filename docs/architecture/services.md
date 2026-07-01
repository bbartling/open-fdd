---
title: Services
parent: Architecture
nav_order: 1
---

# Edge services

All production services run from one GHCR image with different `SERVICE_MODE` values:

```text
ghcr.io/bbartling/openfdd-edge-rust:${OPENFDD_IMAGE_TAG:-latest}
```

## Service modes

| Container | `SERVICE_MODE` | Role |
|-----------|----------------|------|
| `openfdd-bridge` | `bridge` | REST API, JWT auth, React dashboard, Modbus/JSON drivers, historian writes, DataFusion FDD, reports |
| `openfdd-commission` | `commission` | BACnet discover/poll/override scan (`network_mode: host`) |
| `openfdd-haystack-gateway` | `haystack-gateway` | Haystack read/nav/ops against a remote Haystack server |

```text
┌──────────────────────────────────────────────────────────────┐
│  openfdd-bridge (:8080)                                      │
│  REST · JWT · dashboard · historian · DataFusion · MCP APIs  │
└──────────────────────────────────────────────────────────────┘
         │ shared workspace volume
         ▼
┌─────────────────────────┐  ┌────────────────────────────────┐
│ openfdd-commission      │  │ openfdd-haystack-gateway       │
│ BACnet / Modbus poll    │  │ Haystack client (BAS / nHaystack) │
└─────────────────────────┘  └────────────────────────────────┘
```

## Optional profiles

| Profile | Service | Notes |
|---------|---------|-------|
| `caddy-http` / `caddy-tls` | Caddy reverse proxy | TLS termination for LAN ingress |
| `mcp-sidecar` | `openfdd-mcp` | Optional stdio MCP for external agents (Codex, Cursor, OpenClaw, …) |

## MCP binary

The edge image bundles `/usr/local/bin/openfdd-mcp`. Run MCP without a sidecar:

```bash
docker run --rm -i \
  -v ~/open-fdd/workspace:/var/openfdd/workspace \
  --entrypoint openfdd-mcp \
  ghcr.io/bbartling/openfdd-edge-rust:latest
```

## Workspace

All durable site state lives under `workspace/` (bind-mounted). Never delete it.
