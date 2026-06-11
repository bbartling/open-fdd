---
title: Architecture
nav_order: 4
has_children: true
---

# Architecture

Open-FDD v3 edge: **three Docker containers** (`bridge`, `commission`, `mcp-rag`), BACnet polling in **commission**, feather ingest in **bridge**, optional host Caddy and Ollama.

| Page | Topic |
|------|-------|
| [System overview]({% link architecture/overview.md %}) | Components and diagram |
| [Deployment modes]({% link architecture/deployment-modes.md %}) | Local dev, lab LAN, edge production, Caddy HTTP/TLS |
| [Data flow]({% link architecture/data-flow.md %}) | BACnet / Modbus / JSON API → feather → FDD → dashboard |
| [Containers]({% link architecture/containers.md %}) | GHCR images, ports, persistence, retired poll image |
| [Driver framework]({% link drivers/index.md %}) | Shared commissioning pattern for OT sources |

**Operators:** [Quick Start — Docker]({% link quick-start/docker.md %}) — no git clone on the edge host.

**BACnet polling:** [Polling]({% link bacnet/polling.md %}) — commission container only.
