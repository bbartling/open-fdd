---
title: Architecture
nav_order: 4
has_children: true
---

# Architecture

High-level view of the Open-FDD v3 edge stack: **three Docker containers** (`bridge`, `commission`, `mcp-rag`), BACnet polling inside **commission**, historian ingest in **bridge**.

| Page | Topic |
|------|-------|
| [System overview](overview) | Components, diagram, deployment pointer |
| [Data flow](data-flow) | Poll → CSV → feather → FDD → dashboard |
| [Containers](containers) | Images, networks, ports, persistence, reboot |

**Operators:** deploy and upgrade via [Quick Start](../quick-start/docker) — no git clone on the edge host.

**BACnet polling:** [Polling](../bacnet/polling) — commission loop only (no separate poll container).
