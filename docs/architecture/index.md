---
title: Architecture
nav_order: 4
has_children: true
---

# Architecture

Open-FDD v3 edge: **three Docker containers** (`bridge`, `commission`, `mcp-rag`), BACnet polling in **commission**, feather ingest in **bridge**, optional host Caddy and Ollama.

| Page | Topic |
|------|-------|
| [System overview]({{ "/architecture/overview/" | relative_url }}) | Components and diagram |
| [Deployment modes]({{ "/architecture/deployment-modes/" | relative_url }}) | Local dev, lab LAN, edge production, Caddy HTTP/TLS |
| [Data flow]({{ "/architecture/data-flow/" | relative_url }}) | BACnet / Modbus / JSON API → feather → FDD → dashboard |
| [Containers]({{ "/architecture/containers/" | relative_url }}) | GHCR images, ports, persistence, retired poll image |
| [Driver framework]({{ "/drivers/" | relative_url }}) | Shared commissioning pattern for OT sources |

**Operators:** [Quick Start — Docker]({{ "/quick-start/docker/" | relative_url }}) — no git clone on the edge host.

**BACnet polling:** [Polling]({{ "/bacnet/polling/" | relative_url }}) — commission container only.
