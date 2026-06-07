---
title: System overview
parent: Architecture
nav_order: 1
---

# System overview

```
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│  BACnet OT  │────▶│  commission container    │────▶│ samples.csv     │
│   devices   │     │  discover/read/write     │     │ (poll output)   │
└─────────────┘     │  + poll loop (RPM)       │     └────────┬────────┘
                    └──────────────────────────┘              │
                                                              ▼
                    ┌──────────────────────────┐     ┌─────────────────┐
                    │  bridge container          │◀────│ feather historian│
                    │  ingest worker + API + UI  │     │ workspace/data  │
                    └─────────────┬──────────────┘     └─────────────────┘
                                  │
┌─────────────┐     ┌─────────────▼──────────────┐
│  Operator   │◀───▶│  FastAPI + React dashboard │
│  browser    │     │  Rule Lab / FDD / faults   │
└─────────────┘     └────────────────────────────┘
        ▲
   Caddy :80 (host, optional)
```

## Docker edge stack (production)

Three GHCR images — see [Containers](containers):

| Container | BACnet OT | Operator LAN |
|-----------|-----------|--------------|
| **bridge** | No (HTTP only) | Yes, via Caddy `:80` or loopback `:8765` |
| **commission** | Yes (host network, `:47808`) | No (internal `:8767`) |
| **mcp-rag** | No | No (internal `:8090`) |

BACnet **polling** is not a separate container — it runs inside **commission**. The bridge only **ingests** poll CSV into feather.

## Components

| Layer | Responsibility |
|-------|----------------|
| **Operator Bridge** | Auth, REST/WebSocket API, compiled dashboard, Rule Lab, historian ingest |
| **BACnet commission** | Who-Is, read/write (gated), **scheduled poll loop** → `samples.csv` |
| **Historian** | Feather files per point; local-first retention |
| **FDD runner** | `workspace/data/rules_py/*.py` on timer or `POST /api/rules/batch` |
| **Model** | Brick TTL + `model.json` bindings (`fdd_input`, equipment tree) |
| **MCP RAG** | Optional doc retrieval for agent tools |
| **Caddy** | Host reverse proxy `:80` → bridge (typical edge) |
| **Ollama** | Optional host LLM for building insight (not required for FDD) |

## Deployment

IT operators: [Quick Start — Docker](../quick-start/docker) (`docker compose pull`, `restart: unless-stopped`, Docker enabled on boot).

## Optional PyPI-only path

`pip install open-fdd` ships Arrow runtime + playground lint helpers **without** the Operator Bridge UI. Use for offline rule tests or CI. See [Appendix — Python package](../appendix/python-package).
