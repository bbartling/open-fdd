---
title: Architecture
nav_order: 4
has_children: true
---

# Architecture

Open-FDD v3 edge: **three Docker containers** (`bridge`, `commission`, `mcp-rag`), BACnet polling in **commission**, feather ingest in **bridge**, optional host Caddy and Ollama.

| Page | Topic |
|------|-------|
| [System overview](overview) | Components and diagram |
| [Deployment modes](deployment-modes) | Local dev, lab LAN, edge production, Caddy HTTP/TLS |
| [Data flow](data-flow) | BACnet / Modbus / JSON API → feather → FDD → dashboard |
| [Containers](containers) | GHCR images, ports, persistence, retired poll image |
| [Driver framework](../drivers/index) | Shared commissioning pattern for OT sources |

**Operators:** [Quick Start — Docker](../quick-start/docker) — no git clone on the edge host.

**BACnet polling:** [Polling](../bacnet/polling) — commission container only.
